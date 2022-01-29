from .lib import ipython, proto_util, sparkline

import click
import logging
import numbers
import os
import platform
import sys
import time
from typing import Any, Dict, Optional, Sequence, Union
import wandb
from wandb.proto.wandb_internal_pb2 import CheckVersionResponse, FilePusherStats, PollExitResponse

logger = logging.getLogger("wandb")


RUN_NAME_COLOR = "#cdcd00"


class Printer:
    _sampled_history: Optional[Dict[str, Union[Sequence[int], Sequence[float]]]]
    _final_summary: Optional[Dict[str, Any]]
    _poll_exit_response: Optional[PollExitResponse]
    _check_version: Optional[CheckVersionResponse]

    def __init__(self) -> None:
        self._check_version = None
        self._poll_exit_response = None
        self._sampled_history = None
        self._final_summary = None
        
        self._jupyter_progress = None
        self._reporter = None
        self._progress_step = 0

    def _set_run_obj(self, run_obj) -> None:
        pass

    def _display_on_init(self, interface) -> None:
        logger.info("communicating current version")
        check = interface.communicate_check_version(current_version=wandb.__version__)
        if check:
            self._check_version = check
            logger.info(f"got version response {check}")
        self._show_version_info()

    def _show_version_info(self, footer: bool = None) -> None:
        package_problem = False
        if self._check_version.delete_message:
            wandb.termerror(self._check_version.delete_message)
            package_problem = True
        elif self._check_version.yank_message:
            wandb.termwarn(self._check_version.yank_message)
            package_problem = True
        # only display upgrade message if packages are bad or in header
        if not footer or package_problem:
            if self._check_version.upgrade_message:
                wandb.termlog(self._check_version.upgrade_message)

    def _display_on_start(
        self,
        project_url,
        run_url,
        sweep_url,
        run_name,
        sync_dir,
        offline,
        quiet,
        jupyter,
        silent,
        run_obj,
        resumed,
    ) -> None:
        # TODO: make offline mode in jupyter use HTML
        if offline and not quiet:
            message = (
                "W&B syncing is set to `offline` in this directory.  ",
                "Run `wandb online` or set WANDB_MODE=online to enable cloud syncing.",
            )
            if jupyter and ipython.in_jupyter():
                ipython.display_html("<br/>\n".join(message))
            else:
                for m in message:
                    wandb.termlog(m)
        if run_obj and not silent:
            self._display_run(
                project_url,
                run_url,
                sweep_url,
                run_name,
                sync_dir,
                jupyter,
                quiet,
                offline,
                resumed,
            )

    def _display_run(
        self,
        project_url,
        run_url,
        sweep_url,
        run_name,
        sync_dir,
        jupyter,
        quiet,
        offline,
        resumed,
    ) -> None:

        version_str = f"Tracking run with wandb version {wandb.__version__}"
        if resumed:
            run_state_str = "Resuming run"
        else:
            run_state_str = "Syncing run"

        if jupyter:
            sync_dir = "<code>{}</code>".format(sync_dir)
        dir_str = "Run data is saved locally in {}".format(sync_dir)
        if jupyter and ipython.in_jupyter():
            if not wandb.jupyter.maybe_display():
                # TODO: make settings the source of truth
                quiet = wandb.jupyter.quiet()
                sweep_line = (
                    'Sweep page: <a href="{}" target="_blank">{}</a><br/>\n'.format(
                        sweep_url, sweep_url
                    )
                    if sweep_url and not quiet
                    else ""
                )
                docs_html = (
                    ""
                    if quiet
                    else '(<a href="https://docs.wandb.com/integrations/jupyter.html" target="_blank">docs</a>)'
                )  # noqa: E501
                project_html = (
                    ""
                    if quiet
                    else f'<a href="{project_url}" target="_blank">Weights & Biases</a>'
                )
                ipython.display_html(
                    """
                    {} <strong><a href="{}" target="_blank">{}</a></strong> to {} {}.<br/>\n{}
                """.format(  # noqa: E501
                        run_state_str,
                        run_url,
                        run_name,
                        project_html,
                        docs_html,
                        sweep_line,
                    )
                )
        else:
            if not quiet:
                wandb.termlog(version_str)
            wandb.termlog(
                "{} {}".format(run_state_str, click.style(run_name, fg="yellow"))
            )
            emojis = dict(star="", broom="", rocket="")
            if platform.system() != "Windows" and wandb.util.is_unicode_safe(
                sys.stdout
            ):
                emojis = dict(star="⭐️", broom="🧹", rocket="🚀")

            if not quiet:
                wandb.termlog(
                    "{} View project at {}".format(
                        emojis.get("star", ""),
                        click.style(project_url, underline=True, fg="blue"),
                    )
                )
                if sweep_url:
                    wandb.termlog(
                        "{} View sweep at {}".format(
                            emojis.get("broom", ""),
                            click.style(sweep_url, underline=True, fg="blue"),
                        )
                    )
            wandb.termlog(
                "{} View run at {}".format(
                    emojis.get("rocket", ""),
                    click.style(run_url, underline=True, fg="blue"),
                )
            )
            if not quiet:
                wandb.termlog(dir_str)
                if not offline:
                    wandb.termlog("Run `wandb offline` to turn off syncing.")

            api = wandb.apis.internal.Api()
            if api.settings().get("anonymous") == "true":
                wandb.termwarn(
                    "Do NOT share these links with anyone. They can be used to claim your runs."
                )

            print("")

    def _pusher_print_status(
        self,
        offline,
        jupyter,
        progress: FilePusherStats,
        prefix: bool = True,
        done: Optional[bool] = False,
    ) -> None:
        if offline:
            return

        line = " %.2fMB of %.2fMB uploaded (%.2fMB deduped)\r" % (
            progress.uploaded_bytes / 1048576.0,
            progress.total_bytes / 1048576.0,
            progress.deduped_bytes / 1048576.0,
        )

        if self._jupyter_progress:
            percent_done: float
            if progress.total_bytes == 0:
                percent_done = 1
            else:
                percent_done = progress.uploaded_bytes / progress.total_bytes
            self._jupyter_progress.update(percent_done, line)
            if done:
                self._jupyter_progress.close()
        elif not jupyter:
            spinner_states = ["-", "\\", "|", "/"]

            line = spinner_states[self._progress_step % 4] + line
            self._progress_step += 1
            wandb.termlog(line, newline=False, prefix=prefix)

            if done:
                dedupe_fraction = (
                    progress.deduped_bytes / float(progress.total_bytes)
                    if progress.total_bytes > 0
                    else 0
                )
                if dedupe_fraction > 0.01:
                    wandb.termlog(
                        "W&B sync reduced upload amount by %.1f%%             "
                        % (dedupe_fraction * 100),
                        prefix=prefix,
                    )
                # clear progress line.
                wandb.termlog(" " * 79, prefix=prefix)

    def _wait_for_finish(self, interface, offline, jupyter) -> PollExitResponse:
        while True:
            if interface:
                poll_exit_resp = interface.communicate_poll_exit()
            logger.info(f"got exit ret: {poll_exit_resp}")

            if poll_exit_resp:
                done = poll_exit_resp.done
                pusher_stats = poll_exit_resp.pusher_stats
                if pusher_stats:
                    self._pusher_print_status(offline, jupyter, pusher_stats, done=done)
                if done:
                    return poll_exit_resp
            time.sleep(0.1)

    def _display_on_finish(
        self, silent, jupyter, exit_code, offline, quiet, interface
    ) -> None:
        if not silent:
            as_html = jupyter and ipython.in_jupyter()
            # if self._backend:
            #     pid = self._backend._internal_pid
            status_str = "Waiting for W&B process to finish... "
            if not exit_code:
                status = "(success)."
                if as_html:
                    status = f'<strong style="color:green">{status}</strong>'
                status_str += status
            else:
                status = "(failed {}).".format(exit_code)
                if as_html:
                    status = f'<strong style="color:red">{status}</strong>'
                status_str += status
                if not offline:
                    status_str += " Press ctrl-c to abort syncing."
            if as_html:
                sep = "<br/>" if not quiet else ""
                ipython.display_html(sep + status_str)
            else:
                print("")
                wandb.termlog(status_str)

        # Wait for data to be synced
        self._poll_exit_response = self._wait_for_finish(interface, offline, jupyter)

        if interface:
            ret = interface.communicate_get_summary()
            if ret:
                self._final_summary = proto_util.dict_from_proto_list(ret.item)

            sampled = interface.communicate_sampled_history()
            if sampled:
                d: Dict[str, Union[Sequence[int], Sequence[float]]] = {}
                for item in sampled.item:
                    d[item.key] = (
                        item.values_float if item.values_float else item.values_int
                    )
                self._sampled_history = d

    def _append_history(self, logs: str, as_html: bool = False) -> str:
        if not self._sampled_history:
            return logs

        # Only print sparklines if the terminal is utf-8
        if not wandb.util.is_unicode_safe(sys.stdout):
            return logs

        logger.info("rendering history")
        max_len = 0
        history_rows = []
        for key in sorted(self._sampled_history):
            if key.startswith("_"):
                continue
            vals = wandb.util.downsample(self._sampled_history[key], 40)
            if any((not isinstance(v, numbers.Number) for v in vals)):
                continue
            line = sparkline.sparkify(vals)
            history_rows.append((key, line))
            max_len = max(max_len, len(key))
        if not history_rows:
            return logs
        if as_html:
            history_table = '<table class="wandb">'
            for row in history_rows:
                history_table += "<tr><td>{}</td><td>{}</td></tr>".format(*row)
            history_table += "</table>"
            logs += "<h3>Run history:</h3><br/>" + history_table + "<br/>"
        else:
            logs += "Run history:\n"
            history_lines = ""
            format_str = "  {:>%s} {}\n" % max_len
            for row in history_rows:
                history_lines += format_str.format(*row)
            logs += history_lines.rstrip() + "\n\n"
        return logs

    def _append_summary(self, logs: str, as_html: bool = False) -> str:
        if self._final_summary:
            logger.info("rendering summary")
            max_len = 0
            summary_rows = []
            for k, v in sorted(self._final_summary.items()):
                # arrays etc. might be too large. for now we just don't print them
                if k.startswith("_"):
                    continue
                if isinstance(v, str):
                    if len(v) >= 20:
                        v = v[:20] + "..."
                    summary_rows.append((k, v))
                elif isinstance(v, numbers.Number):
                    if isinstance(v, float):
                        v = round(v, 5)
                    summary_rows.append((k, v))
                else:
                    continue
                max_len = max(max_len, len(k))
            if not summary_rows:
                return logs
            if as_html:
                summary_table = '<table class="wandb">'
                for row in summary_rows:
                    summary_table += "<tr><td>{}</td><td>{}</td></tr>".format(*row)
                summary_table += "</table>\n"
                logs += "<h3>Run summary:</h3><br/>" + summary_table
            else:
                format_str = "  {:>%s} {}" % max_len
                summary_lines = "\n".join(
                    [format_str.format(k, v) for k, v in summary_rows]
                )
                logs += f"Run summary:\n{summary_lines}\n\n"
        return logs

    def _append_files(self, logs: str, offline, silent, as_html: bool = False) -> str:
        if not self._poll_exit_response or not self._poll_exit_response.file_counts:
            return logs
        if offline:
            return logs

        logger.info("logging synced files")

        if silent:
            return logs

        file_str = "Synced {} W&B file(s), {} media file(s), {} artifact file(s) and {} other file(s){}".format(  # noqa:E501
            self._poll_exit_response.file_counts.wandb_count,
            self._poll_exit_response.file_counts.media_count,
            self._poll_exit_response.file_counts.artifact_count,
            self._poll_exit_response.file_counts.other_count,
            "\n<br/>" if as_html else "\n",
        )
        logs += file_str
        return logs

    def _append_details(self, logs: str, offline, silent, as_html: bool = False) -> str:
        if as_html:
            logs += ipython.TABLE_STYLES
            logs += '<div class="wandb-row"><div class="wandb-col">\n'
        logs = self._append_history(logs, as_html)
        if as_html:
            logs += '</div><div class="wandb-col">\n'
        logs = self._append_summary(logs, as_html)

        if as_html:
            logs += "</div></div>\n"
        return self._append_files(logs, offline, silent, as_html)

    def _show_local_warning(self, is_local) -> None:
        if not self._poll_exit_response or not self._poll_exit_response.local_info:
            return

        if is_local:
            local_info = self._poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                wandb.termwarn(
                    f"Upgrade to the {latest_version} version of W&B Local to get the latest features. Learn more: http://wandb.me/local-upgrade"
                )

    def _display_on_final(
        self,
        jupyter,
        quiet,
        silent,
        run_url,
        run_name,
        offline,
        log_user,
        log_internal,
        sync_dir,
        is_local,
    ) -> None:
        as_html = jupyter and ipython.in_jupyter()
        if as_html:
            lb = "<br/>\n"
        else:
            lb = "\n"
        # check for warnings and errors, show log file locations
        final_logs = ""
        if self._reporter and not quiet:
            warning_lines = self._reporter.warning_lines
            if warning_lines:
                final_logs += f"Warnings:{lb}"
                for line in warning_lines:
                    final_logs += f"{line}{lb}"
                if len(warning_lines) < self._reporter.warning_count:
                    final_logs += f"More warnings...{lb}"

            error_lines = self._reporter.error_lines
            if error_lines:
                final_logs += f"Errors:{lb}"
                for line in error_lines:
                    final_logs += f"{line}{lb}"
                if len(error_lines) < self._reporter.error_count:
                    final_logs += f"More errors...{lb}"

        if not quiet:
            final_logs += self._append_details(final_logs, offline, silent, as_html)

        if run_url and run_name:
            if as_html:
                final_logs += 'Synced <strong style="color:{}">{}</strong>: <a href="{}" target="_blank">{}</a>{}'.format(
                    RUN_NAME_COLOR, run_name, run_url, run_url, lb
                )
            else:
                final_logs += "Synced {}: {}{}".format(
                    click.style(run_name, fg="yellow"),
                    click.style(run_url, fg="blue"),
                    lb,
                )

        if offline and not quiet:
            final_logs += f"You can sync this run to the cloud by running:{lb}"
            final_logs += click.style(f"wandb sync {sync_dir}{lb}", fg="yellow")

        if not quiet and (log_user or log_internal):
            log_dir = log_user or log_internal or "."
            log_dir = log_dir.replace(os.getcwd(), ".")
            if as_html:
                log_dir = "<code>{}</code>".format(os.path.dirname(log_dir))
            final_logs += "Find logs at: {}{}".format(log_dir, lb)

        if as_html:
            ipython.display_html(final_logs)
        else:
            wandb.termlog(final_logs)

        if not quiet and not offline:
            self._show_version_info(footer=True)
            self._show_local_warning(is_local)
