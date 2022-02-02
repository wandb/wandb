from math import inf
from .lib import ipython, proto_util, sparkline

import click
import itertools
import json
import logging
import numbers
import os
import platform
import sys
import time
from typing import Any, Dict, Optional, Sequence, Union
import wandb
from wandb.proto.wandb_internal_pb2 import (
    CheckVersionResponse,
    FilePusherStats,
    PollExitResponse,
    RunRecord,
)

logger = logging.getLogger("wandb")


RUN_NAME_COLOR = "#cdcd00"


class Printer:
    def __init__(self, html: Optional[bool] = None) -> None:
        self._html = html
        self._progress = ProgressPrinter(self._html)
        self._info = []
        self._warnings = []
        self._errors = []

    def _display(self) -> None:
        if self._info:
            if self._html:
                ipython.display_html("<br/>\n".join(self._info))
            else:
                wandb.termlog("\n".join(self._info))
            self._info = []

        if self._warnings:
            wandb.termwarn("\n".join(self._warnings))
            self._warnings = []

        if self._errors:
            wandb.termerror("\n".join(self._errors))
            self._errors = []


class ProgressPrinter:
    def __init__(self, html: Optional[bool] = None) -> None:
        self._jupyter_progress = ipython.jupyter_progress_bar() if html else None
        self._term_progress = itertools.cycle(["-", "\\", "|", "/"])
        self._html = html

    def update(self, line, percent_done=None) -> None:
        if self._html:
            if self._jupyter_progress:
                self._jupyter_progress.update(percent_done, line)
        else:
            wandb.termlog(f"{next(self._term_progress)} {line}", newline=False)

    def close(self) -> None:
        if self._html:
            if self._jupyter_progress:
                self._jupyter_progress.close()
        else:
            wandb.termlog(" " * 79)


class PrinterManager:
    _sampled_history: Optional[Dict[str, Union[Sequence[int], Sequence[float]]]]
    _final_summary: Optional[Dict[str, Any]]
    _poll_exit_response: Optional[PollExitResponse]
    _check_version: Optional[CheckVersionResponse]
    _run_obj: Optional[RunRecord]

    def __init__(self) -> None:
        self._check_version = None
        self._poll_exit_response = None
        self._run_obj = None

        self._sampled_history = None
        self._final_summary = None

        self._printer = None
        self._html = False
        self._reporter = None

    def _set_run_obj(self, run_obj) -> None:
        self._settings = {
            item.key: json.loads(item.value_json) for item in run_obj.settings.item
        }
        self._run_obj = run_obj

        self._html = self._settings["_jupyter"] and ipython.in_jupyter()
        self._printer = Printer(self._html)

    def _display_on_init(self, interface) -> None:
        logger.info("communicating current version")
        check = interface.communicate_check_version(current_version=wandb.__version__)
        if check:
            self._check_version = check
            logger.info(f"got version response {check}")
        self._append_version_check_info()
        self._printer._display()

    def _display_on_start(self, project_url, run_url, sweep_url,) -> None:

        self._append_sync_offline_info()
        self._append_wandb_version_info()
        self._append_run_info(
            project_url, run_url, sweep_url,
        )
        self._append_sync_dir_info()
        self._printer._display()
        print("")

    def _display_on_finish(self, exit_code, quiet, interface) -> None:

        self._display_exit_status(exit_code, quiet)
        # Wait for data to be synced
        self._poll_exit_response = self._wait_for_finish(interface)

        if interface:
            summary = interface.communicate_get_summary()
            if summary:
                self._final_summary = proto_util.dict_from_proto_list(summary.item)

            sampled = interface.communicate_sampled_history()
            if sampled:
                self._sampled_history = {
                    item.key: item.values_float or item.values_int
                    for item in sampled.item
                }

    def _display_on_final(self, quiet, run_url,) -> None:

        self._append_reporter_info(quiet)

        self._append_history_summary_info(quiet)

        self._append_file_sync_info()
        self._append_run_sync_info(run_url)
        self._append_offline_sync_info(quiet)
        self._append_logging_dir_info(quiet)

        if not quiet and not self._settings["_offline"]:
            self._append_version_check_info(footer=True)
            self._append_local_warning()

        self._printer._display()

    def _append_version_check_info(self, footer: bool = None) -> None:
        package_problem = False
        if self._check_version.delete_message:
            self._printer._errors.append(self._check_version.delete_message)
            package_problem = True
        elif self._check_version.yank_message:
            self._printer._warnings.append(self._check_version.yank_message)
            package_problem = True
        # only display upgrade message if packages are bad or in header
        if not footer or package_problem:
            if self._check_version.upgrade_message:
                self._printer._info.append(self._check_version.upgrade_message)

    def _append_wandb_version_info(self):

        if self._settings["_quiet"] or self._settings["_silent"]:
            return

        self._printer._info.append(
            f"Tracking run with wandb version {wandb.__version__}"
        )

    def _append_sync_offline_info(self) -> None:
        if self._settings["_quiet"] or not self._settings["_offline"]:
            return

        # TODO: make offline mode in jupyter use HTML
        self._printer._info.extend(
            [
                "W&B syncing is set to `offline` in this directory.  ",
                "Run `wandb online` or set WANDB_MODE=online to enable cloud syncing.",
            ]
        )

    def _append_offline_sync_info(self, quiet) -> None:
        if quiet or not self._settings["_offline"]:
            return

        self._info.append("You can sync this run to the cloud by running:")
        if self._html:
            self._printer._info.append(
                f'<code> wandb sync {self._settings["sync_dir"]}<code>'
            )
        else:
            self._printer._info.append(
                click.style(f'wandb sync {self._settings["sync_dir"]}', fg="yellow")
            )

    def _append_sync_dir_info(self):

        if self._settings["_quiet"] or self._settings["_silent"]:
            return

        sync_dir = self._settings["sync_dir"]
        format_str = "Run data is saved locally in {}"
        if self._html:
            self._printer._info.append(format_str.format(f"<code>{sync_dir}</code>"))
        else:
            self._printer._info.append(format_str.format(sync_dir))
            if not self._settings["_offline"]:
                self._printer._info.append("Run `wandb offline` to turn off syncing.")

    def _append_file_sync_info(self) -> None:

        if self._settings["_silent"] or self._settings["_offline"]:
            return

        if not self._poll_exit_response or not self._poll_exit_response.file_counts:
            return

        logger.info("logging synced files")
        file_counts = self._poll_exit_response.file_counts
        self._printer._info.append(
            f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), {file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)"
        )

    def _append_run_sync_info(self, run_url) -> None:
        if not run_url:
            return

        run_name = self._run_obj.display_name

        if self._html:
            run_name = f'<strong style="color:{RUN_NAME_COLOR}">{run_name}</strong>'
            run_url = f'<a href="{run_url}" target="_blank">{run_url}</a>'
        else:
            run_name = click.style(run_name, fg="yellow")
            run_url = click.style(run_url, fg="blue")
        self._printer._info.append(f"Synced {run_name}: {run_url}")

    def _append_run_info(self, project_url, run_url, sweep_url,) -> None:

        if self._settings["_offline"] or self._settings["_silent"]:
            return

        run_state_str = "Resuming run" if self._run_obj.resumed else "Syncing run"
        run_name = self._run_obj.display_name

        if self._html:
            if not wandb.jupyter.maybe_display():

                run_line = f'<strong><a href="{run_url}" target="_blank">{run_name}</a></strong>'
                project_line, sweep_line = "", ""

                if not wandb.jupyter.quiet():  # TODO: make settings the source of truth

                    doc_html = (
                        f'<a href="https://wandb.me/run" target="_blank">docs</a>'
                    )
                    project_html = (
                        f'<a href="{project_url}" target="_blank">Weights & Biases</a>'
                    )
                    project_line = f"to {project_html} ({doc_html})"

                    if sweep_url:
                        sweep_line = f'Sweep page: <a href="{sweep_url}" target="_blank">{sweep_url}</a><br/>\n'

                self._printer._info.append(
                    f"{run_state_str} {run_line} {project_line}<br/>\n{sweep_line}"
                )

        else:
            emojis = dict(star="", broom="", rocket="")
            if platform.system() != "Windows" and wandb.util.is_unicode_safe(
                sys.stdout
            ):
                emojis = dict(star="⭐️", broom="🧹", rocket="🚀")

            self._printer._info.append(
                f'{run_state_str} {click.style(run_name, fg="yellow")}'
            )
            if not self._settings["_quiet"]:
                self._printer._info.append(
                    f'{emojis["star"]} View project at {click.style(project_url, underline=True, fg="blue")}'
                )
                if sweep_url:
                    self._printer._info.append(
                        f'{emojis["broom"]} View sweep at {click.style(sweep_url, underline=True, fg="blue")}'
                    )
            self._printer._info.append(
                f'{emojis["rocket"]} View run at {click.style(run_url, underline=True, fg="blue")}'
            )

            api = wandb.apis.internal.Api()
            if api.settings().get("anonymous") == "true":
                self._printer._warnings.append(
                    "Do NOT share these links with anyone. They can be used to claim your runs."
                )

    def _display_exit_status(self, exit_code, quiet) -> None:
        if self._settings["_silent"]:
            return

        info = ["Waiting for W&B process to finish..."]
        if not exit_code:
            status = "(success)."
            if self._html:
                status = f'<strong style="color:green">{status}</strong>'
            info.append(status)
        else:
            status = f"(failed {exit_code})."
            if self._html:
                status = f'<strong style="color:red">{status}</strong>'
            info.append(status)
            if not self._settings["_offline"]:
                info.append("Press ctrl-c to abort syncing.")

        sep = "<br/>" if not quiet and self._html else ""
        self._printer._info.append(f'{sep}{" ".join(info)}')
        self._printer._display()

    def _pusher_print_status(
        self, progress: FilePusherStats, done: Optional[bool] = False,
    ) -> None:

        if self._settings["_offline"]:
            return

        MB = wandb.util.POW_2_BYTES[2][1]
        line = f"{progress.uploaded_bytes/MB :.2f}MB of {progress.total_bytes/MB:.2f}MB uploaded ({progress.deduped_bytes/MB:.2f}MB deduped)\r"

        percent_done = (
            1.0
            if progress.total_bytes == 0
            else progress.uploaded_bytes / progress.total_bytes
        )

        self._printer._progress.update(line, percent_done)
        if done:
            self._printer._progress.close()

            dedupe_fraction = (
                progress.deduped_bytes / float(progress.total_bytes)
                if progress.total_bytes > 0
                else 0
            )
            if dedupe_fraction > 0.01:
                self._printer._info.append(
                    f"W&B sync reduced upload amount by {dedupe_fraction * 100:.1f}%             "
                )
            self._printer._display()

    def _wait_for_finish(self, interface) -> PollExitResponse:
        while True:
            if interface:
                poll_exit_resp = interface.communicate_poll_exit()
            logger.info(f"got exit ret: {poll_exit_resp}")

            if poll_exit_resp:
                done = poll_exit_resp.done
                pusher_stats = poll_exit_resp.pusher_stats
                if pusher_stats:
                    self._pusher_print_status(pusher_stats, done=done)
                if done:
                    return poll_exit_resp
            time.sleep(0.1)

    def _render_history_info(self, as_html: bool = False) -> Optional[str]:
        if not self._sampled_history:
            return

        # Only print sparklines if the terminal is utf-8
        if not wandb.util.is_unicode_safe(sys.stdout):
            return

        logger.info("rendering history")
        max_len, history_rows = 0, []
        for key, values in sorted(self._sampled_history.items()):
            if key.startswith("_"):
                continue
            downsampled_values = wandb.util.downsample(values, 40)
            if any(
                (not isinstance(value, numbers.Number) for value in downsampled_values)
            ):
                continue
            history_rows.append((key, sparkline.sparkify(downsampled_values)))
            max_len = max(max_len, len(key))
        if not history_rows:
            return
        if as_html:
            history_title = "<h3>Run history:</h3>"
            history_table = "".join(
                ["<tr><td>{}</td><td>{}</td></tr>".format(*row) for row in history_rows]
            )
            history_table = f'<table class="wandb">{history_table}</table>'
            return f"{history_title}<br/>{history_table}<br/>"
        else:
            history_title = "Run history:"
            history_table = "\n".join(
                [("  {:>%s} {}" % max_len).format(*row) for row in history_rows]
            )
            history_table = f"{history_table.rstrip()}\n"
            return f"{history_title}\n{history_table}\n"

    def _render_summary_info(self, as_html: bool = False) -> Optional[str]:
        if not self._final_summary:
            return

        logger.info("rendering summary")
        max_len, summary_rows = 0, []
        for key, value in sorted(self._final_summary.items()):
            # arrays etc. might be too large. for now we just don't print them
            if key.startswith("_"):
                continue
            if isinstance(value, str):
                value = value[:20] + "..." * (len(value) >= 20)
                summary_rows.append((key, value))
            elif isinstance(value, numbers.Number):
                summary_rows.append((key, round(value, 5)))
            else:
                continue
            max_len = max(max_len, len(key))
        if not summary_rows:
            return
        if as_html:
            summary_table = "".join(
                ["<tr><td>{}</td><td>{}</td></tr>".format(*row) for row in summary_rows]
            )
            summary_table = f'<table class="wandb">{summary_table}</table>\n'
            return f"<h3>Run summary:</h3><br/>{summary_table}"
        else:
            summary_table = "\n".join(
                [("  {:>%s} {}" % max_len).format(*row) for row in summary_rows]
            )
            return f"Run summary:\n{summary_table}\n"

    def _append_history_summary_info(self, quiet) -> str:

        if quiet:
            return

        as_html = self._html

        history = self._render_history_info(as_html)
        summary = self._render_summary_info(as_html)

        if not history and not summary:
            return

        if as_html:
            col_format = '<div class="wandb-col">{}</div>\n'
            row_format = '<div class="wandb-row">{}</div>\n'
            table_style = ipython.TABLE_STYLES
        else:
            col_format = row_format = "{}"
            table_style = ""

        row = ""
        if history:
            row += col_format.format(history)
        if summary:
            row += col_format.format(summary)

        self._printer._info.append(table_style + row_format.format(row))

    def _append_local_warning(self) -> None:
        if not self._poll_exit_response or not self._poll_exit_response.local_info:
            return

        if self._settings["is_local"]:
            local_info = self._poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                self._printer._warnings.append(
                    f"Upgrade to the {latest_version} version of W&B Local to get the latest features. Learn more: http://wandb.me/local-upgrade"
                )

    def _append_reporter_info(self, quiet) -> None:
        if quiet or not self._reporter:
            return

        warning_lines = self._reporter.warning_lines
        if warning_lines:
            self._printer._info.append("Warnings:")
            for line in warning_lines:
                self._printer._info.append(f"{line}")
            if len(warning_lines) < self._reporter.warning_count:
                self._printer._info.append("More warnings...")

        error_lines = self._reporter.error_lines
        if error_lines:
            self._printer._info.append("Errors:")
            for line in error_lines:
                self._printer._info.append(f"{line}")
            if len(error_lines) < self._reporter.error_count:
                self._printer._info.append("More errors...")

    def _append_logging_dir_info(self, quiet) -> None:

        log_dir = self._settings["log_user"] or self._settings["log_internal"]

        if quiet or not log_dir:
            return

        log_dir = os.path.dirname(log_dir.replace(os.getcwd(), "."))

        if self._html:
            log_dir = f"<code>{log_dir}</code><br/>\n"
        else:
            log_dir = f"{log_dir}\n"

        self._printer._info.append(f"Find logs at: {log_dir}")
