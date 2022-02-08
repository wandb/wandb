from contextlib import contextmanager
import functools
import json
import logging
import numbers
import os
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
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
    runs: Union["Run", "StreamRecord", Dict[str, "StreamRecord"]],
) -> Generator:
    _runs = (
        (runs,) if not isinstance(runs, dict) else tuple(run for run in runs.values())
    )
    printer = RunPrinter(_runs)  # type: ignore
    yield printer


class RunPrinter:
    _settings: Union[Dict[str, "Settings"], "Settings"]
    _printer: Union["PrinterJupyter", "PrinterTerm"]
    _run_id: Optional[str]

    def __init__(self, runs: Tuple[Union["Run", "StreamRecord"]],) -> None:
        jupyter = all(
            [run._settings._jupyter for run in runs]
        )  # fixme: Temporary solution until we use rich, which has a single console that randers both jupyter and terminal
        self._printer = printer.get_printer(jupyter)
        self._settings = {run._settings.run_id: run._settings for run in runs}
        self._run_id = None if len(runs) > 1 else runs[0]._settings.run_id

    def repeat_for_all(func: Callable) -> Callable:  # type:ignore # noqa: N805
        @functools.wraps(func)
        def wrapper(self, *args: Any, **kwargs: Any) -> Any:  # type:ignore
            for settings in self._settings.values():
                func(self, *args, **kwargs, settings=settings)

        return wrapper

    # repeat_for_all = staticmethod(repeat_for_all)

    # ------------------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------------------
    @repeat_for_all
    def _header_version_check_info(
        self,
        check_version: Optional["CheckVersionResponse"] = None,
        *,
        settings: "Settings",
    ) -> None:

        if not check_version:
            return

        if settings._offline:
            return

        if check_version.delete_message:
            self._printer.display(check_version.delete_message, status="error")
        elif check_version.yank_message:
            self._printer.display(check_version.yank_message, status="warn")

        if check_version.upgrade_message:
            self._printer.display(check_version.upgrade_message)

    @repeat_for_all
    def _header_wandb_version_info(
        self, quiet: Optional[bool] = None, *, settings: "Settings",
    ) -> None:

        self._printer.display(
            f"Tracking run with wandb version {wandb.__version__}",
            off=(quiet or settings._quiet) or settings._silent,
        )

    @repeat_for_all
    def _header_sync_info(
        self, quiet: Optional[bool] = None, *, settings: "Settings",
    ) -> None:

        if settings._offline:
            self._printer.display(
                [
                    f"W&B syncing is set to {self._printer.code('`offline`')} in this directory.  ",
                    f"Run {self._printer.code('`wandb online`')} or set {self._printer.code('WANDB_MODE=online')} to enable cloud syncing.",
                ]
            )
        else:
            info = [
                f"Run data is saved locally in {self._printer.files(settings.sync_dir)}"
            ]
            if not self._printer._html:
                info.append(
                    f"Run {self._printer.code('`wandb offline`')} to turn off syncing."
                )
            self._printer.display(
                info, off=(quiet or settings._quiet) or settings._silent
            )

    @repeat_for_all
    def _header_run_info(
        self, quiet: Optional[bool] = None, *, settings: "Settings",
    ) -> None:

        if settings._offline or settings._silent:
            return

        run_url = settings.run_url
        project_url = settings.project_url
        sweep_url = settings.sweep_url

        run_state_str = "Resuming run" if settings.resumed else "Syncing run"
        run_name = settings.run_name

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
            if not (quiet or settings._quiet):
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

    # ------------------------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------------------------
    @repeat_for_all
    def _footer_exit_status_info(
        self, exit_code: int, *, settings: "Settings",
    ) -> None:

        if settings._silent:
            return

        status = "(success)." if not exit_code else f"(failed {exit_code})."
        info = [
            f"Waiting for W&B process to finish... {self._printer.status(status, bool(exit_code))}"
        ]

        if not settings._offline and exit_code:
            info.append("Press ctrl-c to abort syncing.")

        self._printer.display(f'{" ".join(info)}')

    @repeat_for_all
    def _footer_file_pusher_status_info(
        self,
        pool_exit_response: Optional["PollExitResponse"] = None,
        *,
        settings: "Settings",
    ) -> None:

        if settings._offline:
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

    @repeat_for_all
    def _footer_sync_info(
        self,
        pool_exit_response: Optional["PollExitResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
    ) -> None:

        if settings._silent:
            return

        if settings._offline:
            self._printer.display(
                [
                    "You can sync this run to the cloud by running:",
                    self._printer.code(f"wandb sync {settings.sync_dir}"),
                ],
                off=(quiet or settings.quiet),
            )
        else:
            info = [
                f"Synced {self._printer.name(settings.run_name)}: {self._printer.link(settings.run_url)}"
            ]
            if pool_exit_response and pool_exit_response.file_counts:

                logger.info("logging synced files")
                file_counts = pool_exit_response.file_counts
                info.append(
                    f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), {file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)",
                )
            self._printer.display(info)

    @repeat_for_all
    def _footer_log_dir_info(
        self, quiet: Optional[bool] = None, *, settings: "Settings",
    ) -> None:

        if (quiet or settings.quiet) or settings._silent:
            return

        log_dir = settings.log_user or settings.log_internal
        if log_dir:
            log_dir = os.path.dirname(log_dir.replace(os.getcwd(), "."))
            self._printer.display(f"Find logs at: {self._printer.files(log_dir)}",)

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

    @repeat_for_all
    def _footer_history_summary_info(
        self,
        history: Optional["SampledHistoryResponse"] = None,
        summary: Optional["GetSummaryResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
    ) -> None:

        if (quiet or settings._quiet) or settings._silent:
            return

        panel = []
        history_rows = self._render_history_info(history)
        if history_rows:
            history_grid = self._printer.grid(history_rows, "Run history:",)
            panel.append(history_grid)

        summary_rows = self._render_summary_info(summary)
        if summary_rows:
            summary_grid = self._printer.grid(summary_rows, "Run summary:",)
            panel.append(summary_grid)

        if panel:
            self._printer.display(self._printer.panel(panel),)

    @repeat_for_all
    def _footer_local_warn(
        self,
        poll_exit_response: Optional["PollExitResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
    ) -> None:

        if (quiet or settings.quiet) or settings.silent:
            return

        if settings._offline:
            return

        if not poll_exit_response or not poll_exit_response.local_info:
            return

        if settings.is_local:
            local_info = poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                self._printer.display(
                    f"Upgrade to the {latest_version} version of W&B Local to get the latest features. Learn more: {self._printer.link('http://wandb.me/local-upgrade')}",
                    status="warn",
                )

    @repeat_for_all
    def _footer_version_check_info(
        self,
        check_version: Optional["CheckVersionResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
    ) -> None:

        if not check_version:
            return

        if settings._offline:
            return

        if (quiet or settings._quiet) or settings._silent:
            return

        if check_version.delete_message:
            self._printer.display(check_version.delete_message, status="error")
        elif check_version.yank_message:
            self._printer.display(check_version.yank_message, status="warn")

        # only display upgrade message if packages are bad
        package_problem = check_version.delete_message or check_version.yank_message
        if package_problem and check_version.upgrade_message:
            self._printer.display(check_version.upgrade_message)

    @repeat_for_all
    def _footer_reporter_warn_err(
        self,
        reporter: Optional["Reporter"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
    ) -> None:

        if not settings:
            return

        if (quiet or settings._quiet) or settings.silent:
            return

        if not reporter:
            return

        warning_lines = reporter.warning_lines
        if warning_lines:
            warn = ["Warnings:"]
            warn.extend([f"{line}" for line in warning_lines])
            if len(warning_lines) < reporter.warning_count:
                warn.append("More warnings...")
            self._printer.display(warn,)

        error_lines = reporter.error_lines
        if error_lines:
            error = ["Errors:"]
            error.extend([f"{line}" for line in error_lines])
            if len(error_lines) < reporter.error_count:
                error.append("More errors...")
            self._printer.display(error,)

    # ------------------------------------------------------------------------------
    # STREAMS
    # ------------------------------------------------------------------------------

    # fixme: Temporary hack until we move to rich which allows multiple spinners
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
