from contextlib import contextmanager
import json
import logging
import numbers
import os
from typing import (
    Dict,
    Generator,
    List,
    Optional,
    TYPE_CHECKING,
    Union,
)

import wandb
from wandb.apis.internal import Api

from .lib import printer

if TYPE_CHECKING:
    from .lib.printer import PrinterJupyter, PrinterTerm
    from .lib.reporting import Reporter
    from .service.streams import StreamRecord
    from .wandb_run import Run
    from .wandb_settings import Settings
    from wandb.proto.wandb_internal_pb2 import (
        CheckVersionResponse,
        GetSummaryResponse,
        PollExitResponse,
        SampledHistoryResponse,
    )


logger = logging.getLogger("wandb")


@contextmanager
def run_printer(
    run: Optional[Union["Run", "StreamRecord"]] = None,
    streams: Optional[Dict[str, "StreamRecord"]] = None,
) -> Generator:
    printer = RunPrinter(run=run, streams=streams)
    yield printer


class RunPrinter:
    _settings: Union[Dict[str, "Settings"], "Settings"]
    _printer: Union["PrinterJupyter", "PrinterTerm"]
    _run_id: Optional[str]

    def __init__(
        self,
        run: Optional[Union["Run", "StreamRecord"]] = None,
        streams: Optional[Dict[str, "StreamRecord"]] = None,
    ) -> None:
        self._multiple_runs = False
        if run:
            self._printer = printer.get_printer(run._settings._jupyter)
            self._settings = {run._settings.run_id: run._settings}
            self._run_id = run._settings.run_id
        elif streams:
            jupyter = all([stream._settings._jupyter for stream in streams.values()])
            self._printer = printer.get_printer(jupyter)
            self._settings = {sid: stream._settings for sid, stream in streams.items()}
            self._run_id = None if len(streams) > 1 else list(streams.keys())[0]
        else:
            raise

    @property
    def settings(self) -> "Settings":
        if self._run_id:
            return self._settings[self._run_id]
        else:
            raise

    ##############################################
    # HEADER
    ##############################################
    def _version_check_info(
        self,
        check_version: Optional["CheckVersionResponse"] = None,
        footer: Optional[bool] = None,
        quiet: Optional[bool] = None,
    ) -> None:
        if not check_version:
            return

        if footer and (quiet or self.settings._quiet or self.settings._offline):
            return

        package_problem = False
        if check_version.delete_message:
            self._printer.display(check_version.delete_message, status="error")
            package_problem = True
        elif check_version.yank_message:
            self._printer.display(check_version.yank_message, status="warn")
            package_problem = True
        # only display upgrade message if packages are bad or in header
        if not footer or package_problem:
            if check_version.upgrade_message:
                self._printer.display(check_version.upgrade_message)

    def _header_wandb_version_info(self, quiet: Optional[bool] = None,) -> None:

        if (quiet or self.settings._quiet) or self.settings._silent:
            return

        self._printer.display(f"Tracking run with wandb version {wandb.__version__}")

    def _header_offline_sync_info(self) -> None:
        # TODO: make offline mode in jupyter use HTML
        self._printer.display(
            [
                f"W&B syncing is set to {self._printer.code('`offline`')} in this directory.  ",
                f"Run {self._printer.code('`wandb online`')} or set {self._printer.code('WANDB_MODE=online')} to enable cloud syncing.",
            ]
        )

    def _header_online_sync_info(self, quiet: Optional[bool] = None) -> None:
        if (quiet or self.settings._quiet) or self.settings._silent:
            return

        self._printer.display(
            f"Run data is saved locally in {self._printer.files(self.settings.sync_dir)}"
        )
        if not self._printer._html:
            self._printer.display(
                f"Run {self._printer.code('`wandb offline`')} to turn off syncing."
            )

    def _header_sync_info(self, quiet: Optional[bool] = None) -> None:
        if self.settings._offline:
            self._header_offline_sync_info()
        else:
            self._header_online_sync_info(quiet)

    def _header_sync_dir_info(self, quiet: Optional[bool] = None) -> None:

        if (quiet or self.settings._quiet) or self.settings._silent:
            return

        self._printer.display(
            f"Run data is saved locally in {self._printer.files(self.settings.sync_dir)}"
        )
        if not self.settings._offline and not self._printer._html:
            self._printer.display(
                f"Run {self._printer.code('`wandb offline`')} to turn off syncing."
            )

    def _header_run_info(self, quiet: Optional[bool] = None) -> None:

        if self.settings._offline or self.settings._silent:
            return

        run_url = self.settings.run_url
        project_url = self.settings.project_url
        sweep_url = self.settings.sweep_url

        run_state_str = "Resuming run" if self.settings.resumed else "Syncing run"
        run_name = self.settings.run_name

        if self._printer._html:
            if not wandb.jupyter.maybe_display():

                run_line = f"<strong>{self._printer.link(run_url, run_name)}</strong>"
                project_line, sweep_line = "", ""

                # TODO(settings): make settings the source of truth
                if not wandb.jupyter.quiet():

                    doc_html = self._printer.link("https://wandb.me/run", "docs")

                    project_html = self._printer.link(project_url, "Weights & Biases")
                    project_line = f"to {project_html} ({doc_html})"

                    if sweep_url:
                        sweep_line = (
                            f"Sweep page:  {self._printer.link(sweep_url, sweep_url)}"
                        )

                self._printer.display(
                    [f"{run_state_str} {run_line} {project_line}", sweep_line]
                )

        else:
            self._printer.display(f"{run_state_str} {self._printer.name(run_name)}")
            if not (quiet or self.settings._quiet):
                self._printer.display(
                    f'{self._printer.emoji("star")} View project at {self._printer.link(project_url)}'
                )
                if sweep_url:
                    self._printer.display(
                        f'{self._printer.emoji("broom")} View sweep at {self._printer.link(sweep_url)}'
                    )
            self._printer.display(
                f'{self._printer.emoji("rocket")} View run at {self._printer.link(run_url)}'
            )

            # TODO(settings) use `wandb_settings` (if self.settings.anonymous == "true":)
            if Api().api.settings().get("anonymous") == "true":  # type: ignore
                self._printer.display(
                    "Do NOT share these links with anyone. They can be used to claim your runs.",
                    status="warn",
                )

    ##############################################
    # FOOTER
    ##############################################
    def _footer_exit_status_info(self, exit_code: int) -> None:

        if self.settings._silent:
            return

        status = "(success)." if not exit_code else f"(failed {exit_code})."
        info = [
            f"Waiting for W&B process to finish... {self._printer.status(status, bool(exit_code))}"
        ]

        if not self.settings._offline and exit_code:
            info.append("Press ctrl-c to abort syncing.")

        self._printer.display(f'{" ".join(info)}')

    def _footer_file_pusher_status_info(
        self, pool_exit_response: Optional["PollExitResponse"] = None,
    ) -> None:

        if self.settings._offline:
            return

        if not pool_exit_response:
            return

        progress = pool_exit_response.pusher_stats
        done = pool_exit_response.done

        megabyte = wandb.util.POW_2_BYTES[2][1]
        line = f"{progress.uploaded_bytes/megabyte :.2f} MB of {progress.total_bytes/megabyte:.2f} MB uploaded ({progress.deduped_bytes/megabyte:.2f} MB deduped)\r"

        percent_done = (
            1.0
            if progress.total_bytes == 0
            else progress.uploaded_bytes / progress.total_bytes
        )

        self._printer.progress_update(line, percent_done)
        if done:
            self._printer.progress_close()

            dedupe_fraction = (
                progress.deduped_bytes / float(progress.total_bytes)
                if progress.total_bytes > 0
                else 0
            )
            if dedupe_fraction > 0.01:
                self._printer.display(
                    f"W&B sync reduced upload amount by {dedupe_fraction * 100:.1f}%             "
                )

    def _footer_offline_sync_info(self) -> None:
        self._printer.display(
            [
                "You can sync this run to the cloud by running:",
                self._printer.code(f"wandb sync {self.settings.sync_dir}"),
            ]
        )

    def _footer_online_sync_info(
        self, pool_exit_response: Optional["PollExitResponse"] = None
    ) -> None:
        self._printer.display(
            f"Synced {self._printer.name(self.settings.run_name)}: {self._printer.link(self.settings.run_url)}"
        )

        if self.settings._silent:
            return

        if pool_exit_response and pool_exit_response.file_counts:

            logger.info("logging synced files")
            file_counts = pool_exit_response.file_counts
            self._printer.display(
                f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), {file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)"
            )

    def _footer_sync_info(
        self, pool_exit_response: Optional["PollExitResponse"] = None
    ) -> None:
        if self.settings._offline:
            self._footer_offline_sync_info()
        else:
            self._footer_online_sync_info(pool_exit_response)

    def _footer_log_dir_info(self, quiet: Optional[bool] = None) -> None:
        if quiet or self.settings.quiet:
            return
        log_dir = self.settings.log_user or self.settings.log_internal
        if log_dir:
            log_dir = os.path.dirname(log_dir.replace(os.getcwd(), "."))
            self._printer.display(f"Find logs at: {self._printer.files(log_dir)}")

    def _footer_file_sync_info(
        self, poll_exit_response: Optional["PollExitResponse"] = None
    ) -> None:

        if self.settings._silent or self.settings._offline:
            return

        if not poll_exit_response or not poll_exit_response.file_counts:
            return

        logger.info("logging synced files")
        file_counts = poll_exit_response.file_counts
        self._printer.display(
            f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), {file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)"
        )

    def _render_history_info(
        self, history: Union["SampledHistoryResponse", None]
    ) -> Optional[List[List[str]]]:

        if not history:
            return None

        logger.info("rendering history")

        sampled_history = {
            item.key: wandb.util.downsample(item.values_float or item.values_int, 40)
            for item in history.item
            if not item.key.startswith("_")
        }

        history_rows = []
        for key, values in sorted(sampled_history.items()):
            if any((not isinstance(value, numbers.Number) for value in values)):
                continue
            sparkline = self._printer.sparklines(values)
            if sparkline:
                history_rows.append([key, sparkline])
        return history_rows

    def _render_summary_info(
        self, summary: Union["GetSummaryResponse", None]
    ) -> Optional[List[List[str]]]:

        if not summary:
            return None

        final_summary = {
            item.key: json.loads(item.value_json)
            for item in summary.item
            if not item.key.startswith("_")
        }

        logger.info("rendering summary")
        summary_rows = []
        for key, value in sorted(final_summary.items()):
            # arrays etc. might be too large. for now we just don't print them
            if isinstance(value, str):
                value = value[:20] + "..." * (len(value) >= 20)
                summary_rows.append([key, value])
            elif isinstance(value, numbers.Number):
                value = round(value, 5) if isinstance(value, float) else value
                summary_rows.append([key, str(value)])
            else:
                continue
        return summary_rows

    def _footer_history_summary_info(
        self,
        history: Optional["SampledHistoryResponse"] = None,
        summary: Optional["GetSummaryResponse"] = None,
        quiet: Optional[bool] = None,
    ) -> None:

        if quiet or self.settings._quiet:
            return

        panel = []
        history_rows = self._render_history_info(history)
        if history_rows:
            history_grid = self._printer.grid(
                history_rows,
                f"Run({self._printer.name(self.settings.run_name)}) history:",
            )
            panel.append(history_grid)

        summary_rows = self._render_summary_info(summary)
        if summary_rows:
            summary_grid = self._printer.grid(
                summary_rows,
                f"Run({self._printer.name(self.settings.run_name)}) summary:",
            )
            panel.append(summary_grid)

        if panel:
            self._printer.display(self._printer.panel(panel))

    def _footer_local_warn(
        self,
        poll_exit_response: Optional["PollExitResponse"] = None,
        quiet: Optional[bool] = None,
    ) -> None:

        if (quiet or self.settings.quiet) or self.settings._offline:
            return

        if not poll_exit_response or not poll_exit_response.local_info:
            return

        if self.settings.is_local:
            local_info = poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                self._printer.display(
                    f"Upgrade to the {latest_version} version of W&B Local to get the latest features. Learn more: {self._printer.link('http://wandb.me/local-upgrade')}",
                    status="warn",
                )

    def _footer_reporter_warn_err(
        self, quiet: Optional[bool], reporter: Optional["Reporter"] = None
    ) -> None:

        if (quiet or self.settings._quiet) or not reporter:
            return

        warning_lines = reporter.warning_lines
        if warning_lines:
            self._printer.display("Warnings:")
            self._printer.display([f"{line}" for line in warning_lines])
            if len(warning_lines) < reporter.warning_count:
                self._printer.display("More warnings...")

        error_lines = reporter.error_lines
        if error_lines:
            self._printer.display("Errors:")
            self._printer.display([f"{line}" for line in error_lines])
            if len(error_lines) < reporter.error_count:
                self._printer.display("More errors...")

    ##############################################
    # STREAMS
    ##############################################
    def _footer_streams_file_pusher_status_info(
        self, poll_exit_responses: Optional[Dict[str, "PollExitResponse"]] = None
    ) -> None:
        if not poll_exit_responses:
            return
        if self._run_id:
            self._footer_file_pusher_status_info(poll_exit_responses[self._run_id])
        else:
            self._footer_multiple_runs_file_pusher_status_info(poll_exit_responses)

    def _footer_multiple_runs_file_pusher_status_info(
        self, poll_exit_responses: Dict[str, "PollExitResponse"]
    ) -> None:
        megabyte = wandb.util.POW_2_BYTES[2][1]
        total_files, uploaded, total = 0, 0, 0
        for poll_exit_response in poll_exit_responses.values():
            if poll_exit_response and poll_exit_response.file_counts:
                file_counts = poll_exit_response.file_counts
                total_files += (
                    file_counts.wandb_count
                    + file_counts.media_count
                    + file_counts.artifact_count
                    + file_counts.other_count
                )
            if poll_exit_response and poll_exit_response.pusher_stats:
                pusher_stats = poll_exit_response.pusher_stats
                uploaded += pusher_stats.uploaded_bytes
                total += pusher_stats.total_bytes

        line = f"Processing {len(poll_exit_responses)} runs with {total_files} files ({uploaded/megabyte :.2f} MB/{total/megabyte :.2f} MB)"
        line = "{}{:<{max_len}}\r".format(line, " ", max_len=(80 - len(line)))
        self._printer.progress_update(line)  # type: ignore [call-arg]

        done = all(
            [
                poll_exit_response.done
                for poll_exit_response in poll_exit_responses.values()
                if poll_exit_response
            ]
        )
        if done:
            self._printer.progress_close()
