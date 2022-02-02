from .lib import ipython, proto_util, sparkline

import click
import itertools
import json
import logging
import numbers
import os
import sys
import time
from typing import Any, Dict, Optional, List, Sequence, Union
import wandb
from wandb.proto.wandb_internal_pb2 import (
    CheckVersionResponse,
    FilePusherStats,
    PollExitResponse,
    RunRecord,
)

logger = logging.getLogger("wandb")

from rich.console import Console
from rich.table import Table
from rich import box
from rich.live import Live
from rich._spinners import SPINNERS


class Printer:
    def __init__(self, html: Optional[bool] = None) -> None:
        self._html = html
        self._progress = ProgressPrinter(self._html)
        self._info = []
        self._warnings = []
        self._errors = []
        self._console = Console()

    def _grid_html(self, rows: List[List[str]] = [], title: str = "") -> str:
        def _row_html(row):
            return "".join([f"<td>{cell}</td>" for cell in row])

        grid = "".join([f"<tr>{_row_html(row)}</tr>" for row in rows])
        grid = f"<h3>{title}</h3><br/>{grid}"

        return f'<table class="wandb">{grid}</table>\n'

    def _table_html(self, columns: List[str] = []) -> str:
        # TODO change between table and grid
        col_format = '<div class="wandb-col">{}</div>\n'
        row_format = '<div class="wandb-row">{}</div>\n'
        table = ipython.TABLE_STYLES
        table += row_format.format(
            "".join([col_format.format(column) for column in columns])
        )
        return table

    def _grid_term(self, rows: List[List[str]], title: str) -> str:
        grid = Table.grid()
        if title:
            grid.add_row("[bold blue]wandb[/]: ", f"[bold]{title}[/]")
        for row in rows:
            grid.add_row("[bold blue]wandb[/]: ", *row)
        return grid

    def _table_term(self, columns: List[str], rows: List[List[str]]) -> str:

        table = Table(show_header=True, box=box.ROUNDED)
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*row)
        return table

    def bold(self, text: str) -> str:
        if self._html:
            return f'<span style="font-weight:bold">{text}</span>'
        return f"[b]{text}[/]"

    def files(self, text: str) -> str:
        if self._html:
            return f'<span style="color:magenta">{text}</span>'
        return f"[bold magenta]{text}[/]"

    def code(self, text: str) -> str:
        if self._html:
            return f"<code>{text}<code>"
        # return f"[italic]`{text}`[/]"
        return f"`{text}`"

    def failure(self, text: str) -> str:
        if self._html:
            return f'<span style="color:red">{text}</span>'
        return f"[red]{text}[/]"

    def grid(self, rows: List[List[str]] = [], title: Optional[str] = None) -> str:
        if self._html:
            return self._grid_html(rows, title)
        return self._grid_term(rows, title)

    def link(self, link: str, text: Optional[str] = None) -> str:
        if self._html:
            return f'<a href="{link}" target="_blank">{text or link}</a>'
        return f"[link={link}]{link}[/link]"

    def name(self, text: str) -> str:
        NAME_COLOR = "#cdcd00"
        if self._html:
            return f'<span style="color:{NAME_COLOR}">{text}</span>'
        return f"[{NAME_COLOR}]{text}[/]"

    def success(self, text: str) -> str:
        if self._html:
            return f'<span style="color:green">{text}</span>'
        return f"[green]{text}[/]"

    def table(self, columns: List[str] = [], rows: List[List[str]] = []) -> str:
        if self._html:
            return self._table_html(columns)
        return self._table_term(columns, rows)

    def _display_html(self, text: List[str]) -> None:
        for string in text:
            ipython.display_html(string)

    def _display_term(self, text: List[str]) -> None:
        for string in text:
            if isinstance(string, Table):
                self._console.print(string)
            else:
                self._console.print(
                    "\n".join(
                        [f"[bold blue]wandb[/]: {info}" for info in string.split("\n")]
                    )
                )

    def _display(self) -> None:

        if self._info:
            if self._html:
                self._display_html(self._info)
            else:
                self._display_term(self._info)
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
        self._spinner = itertools.cycle(SPINNERS["dots9"]["frames"])
        self._html = html

        self._term_progress = None

    def update(self, line, percent_done=None) -> None:
        if self._html:
            if self._jupyter_progress:
                self._jupyter_progress.update(percent_done, line)
        else:
            line = f"[bold blue]wandb[/bold blue]: {next(self._spinner)} {line}"
            if self._term_progress is None:
                self._term_progress = Live(line)
                self._term_progress.start()
            else:
                self._term_progress.update(line)

    def close(self) -> None:
        if self._html:
            if self._jupyter_progress:
                self._jupyter_progress.close()
        else:
            self._term_progress.update("[bold blue]wandb[/bold blue]:")
            self._term_progress.stop()


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

        self._printer._info.append("You can sync this run to the cloud by running:")
        self._printer._info.append(
            self._printer.code(f'wandb sync {self._settings["sync_dir"]}')
        )

    def _append_sync_dir_info(self):

        if self._settings["_quiet"] or self._settings["_silent"]:
            return

        sync_dir = self._settings["sync_dir"]
        self._printer._info.append(
            f"Run data is saved locally in {self._printer.files(sync_dir)}"
        )
        if not self._html and not self._settings["_offline"]:
            self._printer._info.append(
                f'Run {self._printer.code("wandb offline")} to turn off syncing.'
            )

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
        self._printer._info.append(
            f"Synced {self._printer.name(run_name)}: {self._printer.link(run_url, run_name)}"
        )

    def _append_run_info(self, project_url, run_url, sweep_url,) -> None:

        if self._settings["_offline"] or self._settings["_silent"]:
            return

        run_state_str = "Resuming run" if self._run_obj.resumed else "Syncing run"
        run_name = self._run_obj.display_name

        if self._html:
            if not wandb.jupyter.maybe_display():

                run_line = f"<span>{self._printer.link(run_url, run_name)}</span>"
                project_line, sweep_line = "", ""

                if not wandb.jupyter.quiet():  # TODO: make settings the source of truth

                    doc_html = self._printer.link("https://wandb.me/run", "docs")
                    project_html = self._printer.link(project_url, "Weights & Biases")
                    project_line = f"to {project_html} ({doc_html})"

                    if sweep_url:
                        sweep_line = f"Sweep page: {self._printer.link(sweep_url)}\n"

                self._printer._info.append(
                    f"{run_state_str} {run_line} {project_line}\n{sweep_line}"
                )

        else:
            self._printer._info.append(
                f"{run_state_str} {self._printer.name(run_name)}"
            )
            if not self._settings["_quiet"]:
                self._printer._info.append(
                    f":star: View project at {self._printer.link(project_url)}"
                )
                if sweep_url:
                    self._printer._info.append(
                        f":broom: View sweep at {self._printer.link(sweep_url)}"
                    )
            self._printer._info.append(
                f":rocket: View run at {self._printer.link(run_url)}"
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
            info.append(self._printer.success("(success)"))
        else:
            info.append(self._printer.failure(f"(failed {exit_code})"))
            if not self._settings["_offline"]:
                info.append("Press ctrl-c to abort syncing.")

        self._printer._info.append(f'{" ".join(info)}')
        self._printer._display()

    def _pusher_print_status(
        self, progress: FilePusherStats, done: Optional[bool] = False
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

    def _render_history_info(self) -> Optional[str]:
        if not self._sampled_history:
            return

        # Only print sparklines if the terminal is utf-8
        if not wandb.util.is_unicode_safe(sys.stdout):
            return

        logger.info("rendering history")
        history_rows = []
        for key, values in sorted(self._sampled_history.items()):
            if key.startswith("_"):
                continue
            downsampled_values = wandb.util.downsample(values, 40)
            if any(
                (not isinstance(value, numbers.Number) for value in downsampled_values)
            ):
                continue
            history_rows.append((key, sparkline.sparkify(downsampled_values)))
        if not history_rows:
            return
        return self._printer.grid(history_rows, "Run History")

    def _render_summary_info(self) -> Optional[str]:
        if not self._final_summary:
            return

        logger.info("rendering summary")
        summary_rows = []
        for key, value in sorted(self._final_summary.items()):
            # arrays etc. might be too large. for now we just don't print them
            if key.startswith("_"):
                continue
            if isinstance(value, str):
                summary_rows.append((key, value[:20] + "..." * (len(value) >= 20)))
            elif isinstance(value, numbers.Number):
                summary_rows.append((key, str(round(value, 5))))
            else:
                continue
        if not summary_rows:
            return
        return self._printer.grid(summary_rows, "Run Summary")

    def _append_history_summary_info(self, quiet) -> str:

        if quiet:
            return

        history = self._render_history_info()
        summary = self._render_summary_info()

        if not self._html:
            if history:
                self._printer._info.extend([history, "\n"])
            if summary:
                self._printer._info.extend([summary, "\n"])
        else:
            self._printer._info.append(self._printer.table([history, summary]))

    def _append_local_warning(self) -> None:
        if not self._poll_exit_response or not self._poll_exit_response.local_info:
            return

        if self._settings["is_local"]:
            local_info = self._poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                self._printer._warnings.append(
                    f"Upgrade to the {latest_version} version of W&B Local to get the latest features. Learn more: {self._printer.link('http://wandb.me/local-upgrade')}"
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

        self._printer._info.append(f"Find logs at: {self._printer.files(log_dir)}")
