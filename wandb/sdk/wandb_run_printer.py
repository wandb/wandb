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

from rich.text import Text

import wandb
from wandb.apis.internal import Api
from wandb.proto.wandb_internal_pb2 import RunExitResult

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


from rich.panel import Panel

# from rich.text import Text
from rich.console import Console, Group
from rich.theme import Theme
from rich.table import Table


custom_theme = Theme(
    {"info": "dim cyan", "warning": "black on yellow", "error": "bold red"}
)

console = Console(theme=custom_theme)


class RunPrinter:
    _settings: Union[Dict[str, "Settings"], "Settings"]
    _printer: Union["PrinterJupyter", "PrinterTerm"]
    _run_id: Optional[str]

    def __init__(
        self,
        runs: Tuple[Union["Run", "StreamRecord"]],
    ) -> None:
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
    def header(
        self,
        quiet: Optional[bool] = None,
        check_version: Optional["CheckVersionResponse"] = None,
        *,
        settings: "Settings",
    ) -> None:

        silence = quiet or settings._quiet or settings._silent

        result = []

        # wandb version
        if not silence:
            result.append(f"Tracking run with wandb version {wandb.__version__}")

        # update wandb version information
        if check_version and not settings._offline:
            if check_version.delete_message:
                result.append(f"[error]{check_version.delete_message}[/]")
            elif check_version.yank_message:
                result.append(f"[warning]{check_version.yank_message}[/]")

            if check_version.upgrade_message:
                result.append(check_version.upgrade_message)

        # wandb sync information
        if settings._offline:
            result.extend(
                [
                    "W&B syncing is set to [code]`offline`[/] in this directory.",
                    "Run [code]`wandb online`[/] or set [code]WANDB_MODE=online[/] to enable cloud syncing.",
                ]
            )
        elif not silence:
            result.append(
                f"Run data is saved locally in [magenta bold]{settings.sync_dir}[/]"
            )
            if not settings._jupyter:
                result.append("Run [code]`wandb offline`[/] to turn off syncing.")

        # basic run/project/sweeps information
        if not (settings._offline or settings._silent):

            run_state_str = "Resuming run" if settings.resumed else "Syncing run"
            result.append(f"{run_state_str} [yellow]{settings.run_name}[/]")

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
        console.print(
            Panel(
                "\n".join(result),
                title=f"[bold yellow]{settings.run_name or settings.run_id}[/]",
                subtitle="[bold]wandb[/]",
            )
        )

    def pre_footer(self):
        # self._footer_exit_status_info(exit_code, settings=settings)
        # self._footer_file_pusher_status_info(poll_exit_response, settings=settings)
        # self._footer_history_summary_info(history, summary, quiet, settings=settings)
        pass

    @repeat_for_all
    def footer(
        self,
        exit_code: int,
        history: Optional["SampledHistoryResponse"],
        summary: Optional["GetSummaryResponse"],
        poll_exit_response: Optional["PollExitResponse"],
        check_version: Optional["CheckVersionResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        settings,
    ):
        if settings.silent:
            return

        result = []

        # exit status
        status = (
            "[green](success)[/]" if not exit_code else f"[red](failed {exit_code})[/]"
        )
        abort = (
            "Press ctrl-c to abort syncing."
            if not settings._offline and exit_code
            else ""
        )
        group = [f"Waiting for W&B process to finish... {status}. {abort}\n"]

        # self._footer_file_pusher_status_info(poll_exit_response, settings=settings)

        # sync info
        if settings._offline and not (quiet or settings.quiet):
            result.extend(
                [
                    "You can sync this run to the cloud by running:",
                    f"[code]wandb sync {settings.sync_dir}[/]",
                ]
            )
        else:
            result.append(
                f"Synced [yellow]{settings.run_name}[/]: [link][blue underline]{settings.run_url}[/][/]"
            )
            if poll_exit_response and poll_exit_response.file_counts:

                logger.info("logging synced files")
                file_counts = poll_exit_response.file_counts
                result.append(
                    f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), {file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)",
                )

        if not (quiet or settings.quiet):
            # logging dirctory
            log_dir = settings.log_user or settings.log_internal
            if log_dir:
                log_dir = os.path.dirname(log_dir.replace(os.getcwd(), "."))
                result.append(
                    f"Find logs at: [magenta]{log_dir}[/]",
                )

            # check version
            if not settings._offline and check_version:
                if check_version.delete_message:
                    result.append(f"[error]{check_version.delete_message}[/]")
                elif check_version.yank_message:
                    result.append(f"[warning]{check_version.yank_message}[/]")

                # only display upgrade message if packages are bad
                package_problem = (
                    check_version.delete_message or check_version.yank_message
                )
                if package_problem and check_version.upgrade_message:
                    result.append(check_version.upgrade_message)

            # local warning
            if (
                settings.is_local
                and poll_exit_response
                and poll_exit_response.local_info
            ):
                local_info = poll_exit_response.local_info
                if local_info.out_of_date and not settings._offline:
                    result.append(
                        f"[warning]Upgrade to the {local_info.version} version of W&B Local to get the latest features.[/] Learn more: [link][blue underline]{('http://wandb.me/local-upgrade')}[/][/]",
                    )

        table = self._footer_history_summary_info(history, summary, settings=settings)
        if table:
            group.append(table)
            group.append("\n")

        group.append("\n".join(result))
        console.print(
            Panel(
                Group(*group),
                title=f"[bold yellow]{settings.run_name or settings.run_id}[/]",
                subtitle="[bold]wandb[/]",
            )
        )

    # ------------------------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------------------------
    @repeat_for_all
    def _footer_exit_status_info(
        self,
        exit_code: int,
        *,
        settings: "Settings",
    ) -> None:

        if settings._silent:
            return

        status = (
            "[green](success).[/]"
            if not exit_code
            else f"[red](failed {exit_code}).[/]"
        )
        info = [f"Waiting for W&B process to finish... {status}"]

        if not settings._offline and exit_code:
            info.append("Press ctrl-c to abort syncing.")

        self._printer.display(f'{" ".join(info)}')

    @repeat_for_all
    def _footer_file_pusher_status_info(
        self,
        poll_exit_response: Optional["PollExitResponse"] = None,
        *,
        settings: "Settings",
    ) -> None:

        if settings._offline:
            return

        if not poll_exit_response:
            return

        progress = poll_exit_response.pusher_stats
        done = poll_exit_response.done

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
        table = Table(expand=True)
        rows = []

        if history:
            logger.info("rendering history")

            history_grid = Table.grid(expand=True)
            history_grid.add_column()
            history_grid.add_column(justify="right")

            sampled_history = {
                item.key: wandb.util.downsample(
                    item.values_float or item.values_int, 40
                )
                for item in history.item
                if not item.key.startswith("_")
            }

            for key, values in sorted(sampled_history.items()):
                if any((not isinstance(value, numbers.Number) for value in values)):
                    continue
                sparkline = self._printer.sparklines(values)
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
            return table

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
            self._printer.display(
                warn,
            )

        error_lines = reporter.error_lines
        if error_lines:
            error = ["Errors:"]
            error.extend([f"{line}" for line in error_lines])
            if len(error_lines) < reporter.error_count:
                error.append("More errors...")
            self._printer.display(
                error,
            )

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
