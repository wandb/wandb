from . import ipython, sparkline

import click
import itertools
import json
import os
import numbers
import platform
import sys
from typing import List, Optional, Union
from urllib.parse import quote
import wandb


class Formater:
    def __init__(self, value: str, html: Optional[bool] = None) -> None:
        self._html = html
        self._value = value

    def __str__(self) -> str:
        return self._value

    def __iadd__(self, other: str) -> "Formater":
        self._value += other
        return self

    def display(self, newline: bool = True, prefix: bool = True) -> None:
        if self._html:
            ipython.display_html(self._value)
        else:
            wandb.termlog(self._value, newline=newline, prefix=prefix)

    @property
    def newline(self) -> "Formater":
        self._value += "<br/>\n" if self._html else "\n"
        return self

    @property
    def code(self) -> "Formater":
        if self._html:
            self._value = f"<code>{self._value}</code>"
        return self

    def link(self, label: Optional[str] = None) -> "Formater":
        if self._html:
            self._value = (
                f'<a href="{self._value}" target="_blank">{label or self._value}</a>'
            )
        else:
            self._value = click.style(self._value, underline=True, fg="blue")
        return self

    @property
    def success(self) -> "Formater":
        if self._html:
            self._value = f'<strong style="color:green">{self._value}</strong>'
        else:
            self._value = click.style(self._value, fg="green")
        return self

    @property
    def failure(self) -> "Formater":
        if self._html:
            self._value = f'<strong style="color:red">{self._value}</strong>'
        else:
            self._value = click.style(self._value, fg="red")
        return self

    @property
    def name(self) -> "Formater":
        if self._html:
            self._value = f'<strong style="color:yellow">{self._value}</strong>'
        else:
            self._value = click.style(self._value, fg="yellow")
        return self

    @property
    def strong(self) -> "Formater":
        self._value = (
            f"<strong>{self._value}</strong>"
            if self._html
            else click.style(self._value, bold=True)
        )
        return self

    def _style(self) -> str:
        if self._html:
            return ipython.TABLE_STYLES
        return ""

    def _div_row(self, string: str) -> str:
        f'<div class="wandb-col">{string}</div>'

    def _div_col(self, string: str) -> str:
        f'<div class="wandb-row">{string}</div>'

    def _cell(self, string: str, cell_size: Optional[int] = None) -> str:
        if self._html:
            return f"<td>{string}</td>"
        return f"{string:>{cell_size or 1}} "

    def _row(self, row: List[str], cell_size: Optional[int] = None) -> str:
        row = "".join([self._cell(cell, cell_size) for cell in row])
        if self._html:
            row = f"<tr>{row}</tr>"
        return row

    def _title(self, title: str) -> str:
        if self._html:
            return f"<h3>{title}</h3>"
        return title

    def _table(self, table: List[str], cell_size: Optional[int] = None) -> str:
        table = "\n".join([f"{self._row(row, cell_size)}" for row in table])
        if self._html:
            table = f'<table class="wandb">{table}</table>'
        return table

    def table(self, title: str, cell_size: Optional[int] = None) -> "Formater":
        newline = "<br/>" if self._html else "\n"
        self._value = (
            f"{self._style()}{self._title(title)}{newline}{self._table(self._value)}"
        )
        return self

    @property
    def panel(self) -> "Formater":
        if self._html:
            panel = self._div_row(
                "\n".join([self._div_col(cell) for cell in self._value])
            )
            self._value = f"{self._style()}\n{panel}"
        else:
            self._value = "\n".join([cell for cell in self._value])
        return self


class Printer:
    def __init__(self,) -> None:

        self._reporter = ""

        self._spinner = itertools.cycle(["-", "\\", "|", "/"])

        self._info = []
        self._warnings = []
        self._errors = []

    def display(self) -> None:
        while self._info:
            info = self._info.pop(0)
            self._display(info)

        while self._warnings:
            warning = self._warnings.pop(0)
            wandb.termwarn(warning)

        while self._errors:
            error = self._errors.pop(0)
            wandb.termerror(error)

    def _display(self, string: Union[str, Formater]) -> None:
        # self._html is not safe TODO fix this
        Formater(str(string), self._html).display()

    def _display_on_init(self, interface) -> None:
        self._append_version_info(interface)
        self.display()

    def _display_on_start(self, interface) -> None:
        self._append_sync_offline_info()
        self._append_run_info(interface)

        self.display()
        print("")

    def _display_on_finish(self, exit_code, interface) -> None:
        self._append_status(exit_code)
        self.display()
        # Wait for data to be synced
        self._wait_for_finish(interface)

        self._display_panel(interface)

    def _display_on_final(self) -> None:
        #  self._append_reporter(self._reporter)
        self._append_file_counts()

        self._append_sync_info()
        self._append_log_info()

        self._append_local_warning()
        self._append_version_info(header=False)

        self.display()

    def _append_version_info(self, interface=None, header: bool = True) -> None:
        if self._quiet:
            return

        if self._offline:
            return

        try:
            check = interface.communicate_check_version(
                current_version=wandb.__version__
            )
            self.check = check
        except:
            pass

        package_problem = False
        if self.check.delete_message:
            self._errors.append(self.check.delete_message)
            package_problem = True
        elif self.check.yank_message:
            self._warnings.append(self.check.yank_message)
            package_problem = True
        # only display upgrade message if packages are bad or in header
        if package_problem or header:
            if self.check.upgrade_message:
                self._info.append(self.check.upgrade_message)

    def _append_sync_offline_info(self) -> None:
        if self._quiet:
            return

        # TODO: make offline mode in jupyter use HTML
        if self._offline:
            self._info.append("W&B syncing is set to `offline` in this directory.  ")
            self._info.append(
                "Run `wandb online` or set WANDB_MODE=online to enable cloud syncing."
            )

    def _append_run_info(self, interface=None) -> None:
        if self._silent:
            return

        run_info = "Resuming run" if self._resumed else "Syncing run"
        if self._html:
            if not wandb.jupyter.maybe_display():
                # TODO: make settings the source of truth
                self._quiet = wandb.jupyter.quiet()

                run_html = (
                    Formater(self._run_url, self._html).link(self._run_name).strong
                )

                project_html, docs_html, sweep_line = "", "", ""
                if not self._quiet:

                    project_html = f'to {Formater(self._project_url, self._html).link(label="Weights & Biases")}'

                    docs_html = (
                        f'({Formater("https://wandb.me/run", self._html).link("docs")})'
                    )

                    if self._sweep_url:
                        sweep_line = f"Sweep page: {Formater(self._sweep_url, self._html).link()}"

                self._info.append(
                    f"{run_info} {run_html} {project_html} {docs_html}.<br/>\n{sweep_line}"
                )

        else:
            emojis = dict()
            if platform.system() != "Windows" and wandb.util.is_unicode_safe(
                sys.stdout
            ):
                emojis = dict(star="⭐️", broom="🧹", rocket="🚀")

            if not self._quiet:
                self._info.append(
                    f"Tracking run with wandb version {wandb.__version__}"
                )

            self._info.append(f"{run_info} {Formater(self._run_name, self._html).name}")

            if not self._quiet:
                self._info.append(
                    f'{emojis.get("star", "")} View project at {Formater(self._project_url, self._html).link()}'
                )
                if self._sweep_url:
                    self._info.append(
                        f'{emojis.get("broom", "")} View sweep at {Formater(self._sweep_url, self._html).link()}'
                    )
            self._info.append(
                f'{emojis.get("rocket", "")} View run at {Formater(self._run_url, self._html).link()}'
            )
            if not self._quiet:
                self._info.append(
                    f"Run data is saved locally in {Formater(self._sync_dir, html=self._html).code}"
                )
                if not self._offline:
                    self._info.append("Run `wandb offline` to turn off syncing.")

    def _append_status(self, exit_code: int) -> None:
        if self._silent:
            return

        status_str = "Waiting for W&B process to finish... "
        status_str = f'{"<br/>" if self._html and not self._quiet else ""}{status_str}'

        if not exit_code:
            status = Formater("(success).", self._html).success
        else:
            status = Formater(f"(failed {exit_code}).", self._html).failure
            if not self._offline:
                status += " Press Ctrl-c to abort syncing."

        self._info.append(f"{status_str} {status}")

    def _display_pusher_progress(self, progress, done: Optional[bool] = False,) -> None:

        MB = wandb.util.POW_2_BYTES[2][1]
        line = f" {progress.uploaded_bytes/MB:.2f}MB of {progress.total_bytes/MB:.2f}MB uploaded ({progress.deduped_bytes/MB:.2f}MB deduped)\r"

        # TODO fix jupyter and add progress for terminal
        # if self._jupyter_progress:
        if False:
            percent_done: float = 1.0 if progress.total_bytes == 0 else progress.uploaded_bytes / progress.total_bytes
            self._jupyter_progress.update(percent_done, line)
            if done:
                self._jupyter_progress.close()
        elif not self._html:

            wandb.termlog(f"{next(self._spinner)}{line}", newline=False)

            if done:
                # clear progress line.
                wandb.termlog(" " * 79, newline=True)

                dedupe_fraction = (
                    progress.deduped_bytes / float(progress.total_bytes)
                    if progress.total_bytes > 0
                    else 0
                )
                if dedupe_fraction > 0.01:
                    wandb.termlog(
                        f"W&B sync reduced upload amount by {dedupe_fraction * 100:.1f}%",
                    )

    def _wait_for_finish(self, interface):
        import time

        done = False
        while not done:
            if interface:
                poll_exit_resp = interface.communicate_poll_exit()

            if poll_exit_resp:
                done = poll_exit_resp.done
                pusher_stats = poll_exit_resp.pusher_stats
                if pusher_stats:
                    if not self._offline:
                        self._display_pusher_progress(pusher_stats, done=done)
            time.sleep(0.1)

        self._poll_exit_response = poll_exit_resp

    def _display_panel(self, interface=None) -> None:

        summary = interface.communicate_get_summary()
        history = interface.communicate_sampled_history()
        values = []

        history = self._format_history(history)
        if history:
            values.append(history)

        summary = self._format_summary(summary)
        if summary:
            values.append(summary)

        if values:
            self._display(Formater(values, self._html).panel)

    def _format_history(self, sampled_history) -> Optional[str]:

        # Only print sparklines if the terminal is utf-8
        if not wandb.util.is_unicode_safe(sys.stdout) or not sampled_history:
            return

        sampled_history = {
            item.key: wandb.util.downsample(item.values_float or item.values_int, 40)
            for item in sampled_history.item
            if not item.key.startswith("_")
        }
        history, max_len = [], 0
        for key, values in sorted(sampled_history.items()):
            if all((isinstance(value, numbers.Number) for value in values)):
                history.append((key, sparkline.sparkify(values)))
                max_len = max(max_len, len(key))

        if history:
            return str(
                Formater(history, self._html)
                .table(title="Run history:", cell_size=max_len)
                .newline
            )

    def _format_summary(self, summary) -> Optional[str]:

        if not summary:
            return

        summary = {
            item.key: json.loads(item.value_json)
            for item in summary.item
            if not item.key.startswith("_")
        }

        summary_rows, max_len = [], 0
        for key, value in sorted(summary.items()):
            # arrays etc. might be too large. for now we just don't print them
            if isinstance(value, str):
                summary_rows.append((key, value[:20] + "..." * len(value) >= 20))
            elif isinstance(value, numbers.Number):
                summary_rows.append((key, round(value, 5)))
            else:
                continue
            max_len = max(max_len, len(key))

        if summary_rows:
            return str(
                Formater(summary_rows, self._html)
                .table(title="Run summary:", cell_size=max_len)
                .newline
            )

    def _append_reporter(self, reporter):
        if self._quiet:
            return

        if not reporter:
            return

        # check for warnings and errors, show log file locations
        result = ""
        warning_lines = reporter.warning_lines
        if warning_lines:
            result += f"Warnings:{self.newline(self._html)}"
            for line in warning_lines:
                result += f"{line}{self.newline(self._html)}"
            if len(warning_lines) < reporter.warning_count:
                result += f"More warnings...{self.newline(self._html)}"

        error_lines = reporter.error_lines
        if error_lines:
            result += f"Errors:{self.newline(self._html)}"
            for line in error_lines:
                result += f"{line}{self.newline(self._html)}"
            if len(error_lines) < reporter.error_count:
                result += f"More errors...{self.newline(self._html)}"

        self._reporter = result

    def _append_sync_info(self) -> None:

        self._info.append(
            f"Synced {Formater(self._run_name, self._html).name}: {Formater(self._run_url, html=self._html).link()}"
        )
        if not self._quiet and self._offline:
            self._info.append("You can sync this run to the cloud by running:")
            self._info.append(Formater(f"wandb sync {self._sync_dir}", self._html).name)

    def _append_log_info(self) -> None:
        if self._quiet:
            return

        log_dir = self._log_user or self._log_internal
        if log_dir:
            log_dir = (log_dir or ".").replace(os.getcwd(), ".")
            log_dir = Formater(os.path.dirname(log_dir), html=self._html).code.newline
            self._info.append(f"Find logs at: {log_dir}")

    def _append_file_counts(self) -> None:
        if self._offline and self._silent:
            return

        if not (self._poll_exit_response and self._poll_exit_response.file_counts):
            return

        file_counts = self._poll_exit_response.file_counts
        self._info.append(
            f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), {file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)"
        )

    def _append_local_warning(self) -> None:
        if not (self._poll_exit_response and self._poll_exit_response.local_info):
            return

        if self._offline:
            return

        if not self._quiet and self._is_local:
            local_info = self._poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                self._warnings.append(
                    f"Upgrade to the {latest_version} version of W&B Local to get the latest features. Learn more: http://wandb.me/local-upgrade"
                )

    def _append_anonymous_warning(self):
        api = wandb.api.internal.Api()
        if api.settings().get("anonymous") == "true":
            self._warnings.append(
                "Do NOT share these links with anyone. They can be used to claim your runs."
            )

    def _set_run_obj(self, run_obj) -> None:
        import json

        # TODO replace with run_obj message

        settings = {
            item.key: json.loads(item.value_json) for item in run_obj.settings.item
        }

        self._html = settings["_jupyter"] and ipython.in_jupyter()

        self._offline = settings["_offline"]
        self._silent = settings["_silent"]
        self._quiet = settings["quiet"]

        self._sync_dir = settings["sync_dir"]
        self._log_user = settings["log_user"]
        self._log_internal = settings["log_internal"]
        self._is_local = settings["is_local"]

        app_url = wandb.util.app_url(settings["base_url"])
        entity = quote(run_obj.entity)
        project = quote(run_obj.project)
        run_id = quote(run_obj.run_id)
        sweep_id = quote(run_obj.sweep_id)

        self._project_url = f"{app_url}/{entity}/{project}"
        self._run_url = f"{self._project_url}/runs/{run_id}"

        self._sweep_url = f"{self._project_url}/sweeps/{sweep_id}" if sweep_id else None
        self._run_name = run_obj.display_name
        self._resumed = run_obj.resumed
