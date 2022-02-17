from contextlib import contextmanager
import functools
import json
import logging
import numbers
import os
import re
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
from wandb.old import settings

from .lib.printer import sparklines

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


from rich.panel import Panel

from rich.text import Text
from rich.console import Console, group
from rich.theme import Theme
from rich.table import Table

from rich.live import Live

# from rich.spinner import Spinner
# from rich.progress import Progress, SpinnerColumn
from rich.status import Status


custom_theme = Theme(
    {"info": "dim cyan", "warning": "black on yellow", "error": "bold red"}
)

console = Console(theme=custom_theme)


class RunPrinter:
    _settings: Union[Dict[str, "Settings"], "Settings"]
    _printer: Union["PrinterJupyter", "PrinterTerm"]
    _run_id: Optional[str]

    def __init__(self, runs: Tuple[Union["Run", "StreamRecord"]],) -> None:
        self._settings = {run._settings.run_id: run._settings for run in runs}
        # self._run_id = None if len(runs) > 1 else runs[0]._settings.run_id

        self.spinner = {
            run._settings.run_id: Status("", console=console) for run in runs
        }
        # for spinner in self.spinner.values():
        #     spinner.start()
        # self.lives = {
        #     run._settings.run_id: Live("", console=console, refresh_per_second=4)
        #     for run in runs
        # }

    def repeat_for_all(func: Callable) -> Callable:  # type:ignore # noqa: N805
        @functools.wraps(func)
        def wrapper(self, *args: Any, **kwargs: Any) -> Any:  # type:ignore
            for sid in self._settings:
                console.print(
                    Panel(
                        func(self, *args, **kwargs, sid=sid),
                        title=f"[bold yellow]{self._settings[sid].run_name or self._settings[sid].run_id}[/]",
                        subtitle="[bold]wandb[/]",
                        subtitle_align="right",
                    )
                )

        return wrapper

    # repeat_for_all = staticmethod(repeat_for_all)

    # ------------------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------------------
    @repeat_for_all
    @group()
    def header(
        self,
        quiet: Optional[bool] = None,
        check_version: Optional["CheckVersionResponse"] = None,
        *,
        sid: str,
    ) -> None:

        yield from self._header_wandb_version(check_version, quiet, sid=sid)
        # wandb sync information
        yield from self._header_sync_info(quiet, sid=sid)
        # basic run/project/sweeps information
        yield from self._header_run_info(quiet, sid=sid)

    def _header_sync_info(self, quiet: Optional[bool] = None, *, sid: str) -> List[str]:

        settings = self._settings[sid]
        if quiet or settings._quiet:
            return []

        if settings._offline:
            return [
                "W&B syncing is set to [code]`offline`[/] in this directory.",
                "Run [code]`wandb online`[/] or set [code]WANDB_MODE=online[/] to enable cloud syncing.",
            ]
        elif not settings._silent:
            result = [
                f"Run data is saved locally in [magenta bold]{settings.sync_dir}[/]"
            ]
            if not settings._jupyter:
                result.append("Run [code]`wandb offline`[/] to turn off syncing.")
            return result
        return []

    def _header_wandb_version(
        self,
        check_version: Optional["CheckVersionResponse"],
        quiet: Optional[bool] = None,
        *,
        sid: str,
    ) -> List[str]:

        settings = self._settings[sid]
        result = []
        # wandb version
        if not (quiet or settings._quiet or settings._silent):
            result.append(f"Tracking run with wandb version {wandb.__version__}")

        # update wandb version information
        if check_version and not settings._offline:
            if check_version.delete_message:
                result.append(f"[error]{check_version.delete_message}[/]")
            elif check_version.yank_message:
                result.append(f"[warning]{check_version.yank_message}[/]")

            if check_version.upgrade_message:
                result.append(check_version.upgrade_message)
        return result

    def _header_run_info(self, quiet: Optional[bool] = None, *, sid: str) -> List[str]:
        settings = self._settings[sid]

        if settings.silent or settings._offline:
            return []

        run_state_str = "Resuming run" if settings.resumed else "Syncing run"
        result = [f"{run_state_str} [yellow]{settings.run_name}[/]"]
        # quiet = quiet or (settings._jupyter and wandb.jupyter.quiet())
        if not (quiet or settings._quiet):
            result.append(
                f":star: View project at [link][blue underline]{settings.project_url}[/][/]"
            )
            if settings.sweep_url:
                result.append(
                    f":broom: View sweep at [link][blue underline]{settings.sweep_url}[/][/]"
                )
        result.append(
            f":rocket: View run at [link][blue underline]{settings.run_url}[/][/]"
        )
        # result.append(
        #     ":page_facing_up: View documentation at [link][blue underline]https://wandb.me/run[/][/]"
        # )
        if Api().settings().get("anonymous") == "true":
            result.append(
                "[warning]Do NOT share these links with anyone. They can be used to claim your runs.[/]"
            )
        return result

    # ------------------------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------------------------

    @repeat_for_all
    def spinner_update(
        self, poll_exit_response: Optional["PollExitResponse"] = None, *, sid: str,
    ):

        yield from self._footer_file_pusher_status_info(poll_exit_response, sid=sid)

    def _footer_file_pusher_status_info(
        self, poll_exit_response: Optional["PollExitResponse"] = None, *, sid: str,
    ) -> None:

        settings = self._settings[sid]

        if settings._offline:
            return []

        if not poll_exit_response:
            return []

        progress = poll_exit_response.pusher_stats
        done = poll_exit_response.done

        if not self.spinner[sid]._live._started:
            self.spinner[sid].start()

        if not done:
            megabyte = wandb.util.POW_2_BYTES[2][1]
            line = f"{progress.uploaded_bytes/megabyte :.2f} MB of {progress.total_bytes/megabyte:.2f} MB uploaded ({progress.deduped_bytes/megabyte:.2f} MB deduped)"
            return self.spinner[sid].update(line)

        # percent_done = (
        #     1.0
        #     if progress.total_bytes == 0
        #     else progress.uploaded_bytes / progress.total_bytes
        # )

        self.spinner[sid].stop()
        return []
        # dedupe_fraction = (
        #     progress.deduped_bytes / float(progress.total_bytes)
        #     if progress.total_bytes > 0
        #     else 0
        # )
        # if dedupe_fraction > 0.01:
        #     self._printer.display(
        #         f"W&B sync reduced upload amount by {dedupe_fraction * 100:.1f}%             "
        #     )

    @repeat_for_all
    @group()
    def footer(
        self,
        exit_code: int,
        history: Optional["SampledHistoryResponse"],
        summary: Optional["GetSummaryResponse"],
        poll_exit_response: Optional["PollExitResponse"],
        check_version: Optional["CheckVersionResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        sid,
    ):

        # yield from self._footer_exit_status_info(exit_code, sid=sid)
        # # yield from self._footer_file_pusher_status_info(
        # #     poll_exit_response, sid=sid
        # # )  # TODO
        yield from self._footer_history_summary_info(history, summary, sid=sid)
        yield from self._footer_sync_info(poll_exit_response, quiet, sid=sid)
        yield from self._footer_log_dir_info(quiet, sid=sid)
        yield from self._footer_check_version(check_version, quiet, sid=sid)
        yield from self._footer_check_local_warn(poll_exit_response, quiet, sid=sid)

    def _footer_exit_status_info(self, exit_code: int, *, sid: str,) -> str:
        settings = self._settings[sid]

        if settings._silent:
            return []

        status = (
            "[green](success).[/]"
            if not exit_code
            else f"[red](failed {exit_code}).[/]"
        )
        abort_cmd = (
            "Press ctrl-c to abort syncing."
            if not settings._offline and exit_code
            else ""
        )
        return [f"Waiting for W&B process to finish... {status} {abort_cmd}"]

    def _footer_sync_info(
        self,
        poll_exit_response: Optional["PollExitResponse"],
        quiet: Optional[bool] = None,
        *,
        sid: str,
    ) -> str:
        settings = self._settings[sid]

        if settings.silent:
            return []

        if settings._offline:
            if not (quiet or settings.quiet):
                return [
                    f"You can sync this run to the cloud by running: [code]wandb sync {settings.sync_dir}[/]"
                ]
        else:
            sync_online = [
                f"Synced [yellow]{settings.run_name}[/]: [link][blue underline]{settings.run_url}[/][/]"
            ]
            if poll_exit_response and poll_exit_response.file_counts:

                logger.info("logging synced files")
                file_counts = poll_exit_response.file_counts
                sync_online.append(
                    f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), {file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)"
                )
            return sync_online

    def _footer_log_dir_info(self, quiet: Optional[bool] = None, *, sid: str) -> str:
        settings = self._settings[sid]

        text = []
        if (quiet or settings.quiet) or settings.silent:
            return text

        # logging dirctory
        log_dir = settings.log_user or settings.log_internal
        if log_dir:
            log_dir = os.path.dirname(log_dir.replace(os.getcwd(), "."))
            text.append(f"Find logs at: [magenta]{log_dir}[/]")
        return text

    def _footer_check_version(
        self,
        check_version: Optional["CheckVersionResponse"],
        quiet: Optional[bool] = None,
        *,
        sid: str,
    ) -> str:
        settings = self._settings[sid]

        text = []
        if (quiet or settings.quiet) or settings.silent:
            return text

        if settings._offline or not check_version:
            return text

        # check version
        if check_version.delete_message:
            text.append(f"[error]{check_version.delete_message}[/]")
        elif check_version.yank_message:
            text.append(f"[warning]{check_version.yank_message}[/]")

        # only display upgrade message if packages are bad
        package_problem = check_version.delete_message or check_version.yank_message
        if package_problem and check_version.upgrade_message:
            text.append(f"{check_version.upgrade_message}")

        return text

    def _footer_check_local_warn(
        self,
        poll_exit_response: Optional["PollExitResponse"],
        quiet: Optional[bool] = None,
        *,
        sid: str,
    ) -> str:
        settings = self._settings[sid]
        text = []
        if (quiet or settings.quiet) or settings.silent or settings._offline:
            return text

        if not (poll_exit_response or poll_exit_response.local_info):
            return text

        # local warning
        local_info = poll_exit_response.local_info
        if settings.is_local and local_info.out_of_date:
            text = [
                f"[warning]Upgrade to the {local_info.version} version of W&B Local to get the latest features.[/] Learn more: [link][blue underline]{('http://wandb.me/local-upgrade')}[/][/]"
            ]

        return text

    def _footer_history_summary_info(
        self,
        history: Optional["SampledHistoryResponse"] = None,
        summary: Optional["GetSummaryResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        sid: str,
    ) -> Union["Table", str]:
        settings = self._settings[sid]
        if (quiet or settings._quiet) or settings._silent:
            return []

        table = Table(expand=True)
        rows = []
        if history:
            logger.info("rendering history")

            sampled_history = {
                item.key: wandb.util.downsample(
                    item.values_float or item.values_int, 40
                )
                for item in history.item
                if not item.key.startswith("_")
            }

            history_grid = Table.grid(expand=True)
            history_grid.add_column()
            history_grid.add_column(justify="right")

            for key, values in sorted(sampled_history.items()):
                if all((isinstance(value, numbers.Number) for value in values)):
                    sparkline = sparklines(values)
                    if sparkline:
                        history_grid.add_row(key, sparkline)

            if history_grid.row_count > 0:
                table.add_column("Run history:", justify="center")
                rows.append(history_grid)

        if summary:
            summary_grid = Table.grid(expand=True)
            summary_grid.add_column()
            summary_grid.add_column(justify="right")

            final_summary = {
                item.key: json.loads(item.value_json)
                for item in summary.item
                if not item.key.startswith("_")
            }

            logger.info("rendering summary")
            for key, value in sorted(final_summary.items()):
                # arrays etc. might be too large. for now we just don't print them
                if isinstance(value, str):
                    value = value[:20] + "..." * (len(value) >= 20)
                    summary_grid.add_row(key, value)
                elif isinstance(value, numbers.Number):
                    value = (
                        str(round(value, 5)) if isinstance(value, float) else str(value)
                    )
                    summary_grid.add_row(key, value)
                else:
                    continue
            if summary_grid.row_count > 0:
                table.add_column("Run summary:", justify="center")
                rows.append(summary_grid)

        if rows:
            table.add_row(*rows)
            return [table]
        return []

    @repeat_for_all
    def _footer_reporter_warn_err(
        self,
        reporter: Optional["Reporter"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
    ) -> None:

        if not settings.silent:
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
