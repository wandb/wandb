# Note: this is a helper printer class, this file might go away once we switch to rich console printing

from abc import abstractmethod
import itertools
import platform
import sys
from typing import List, Optional, Tuple, Union

import click
import wandb

from . import ipython, sparkline


class _Printer:
    def sparklines(self, series: List[Union[int, float]]) -> Optional[str]:
        # Only print sparklines if the terminal is utf-8
        if wandb.util.is_unicode_safe(sys.stdout):
            return sparkline.sparkify(series)
        return None

    def abort(
        self,
    ) -> str:
        return "Control-C" if platform.system() != "Windows" else "Ctrl-C"

    def display(
        self,
        text: Union[str, List[str], Tuple[str]],
        *,
        status: Optional[str] = None,
        off: Optional[bool] = None,
    ) -> None:
        if not off:
            self._display(text, status=status)

    @abstractmethod
    def _display(
        self,
        text: Union[str, List[str], Tuple[str]],
        *,
        status: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def code(self, text: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def name(self, text: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def link(self, link: str, text: Optional[str] = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def emoji(self, name: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def status(self, text: str, failure: Optional[bool] = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def files(self, text: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def grid(self, rows: List[List[str]], title: Optional[str] = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def panel(self, columns: List[str]) -> str:
        raise NotImplementedError


class PrinterTerm(_Printer):
    def __init__(self) -> None:
        super().__init__()
        self._html = False
        self._progress = itertools.cycle(["-", "\\", "|", "/"])

    def _display(
        self, text: Union[str, List[str], Tuple[str]], *, status: Optional[str] = None
    ) -> None:
        text = "\n".join(text) if isinstance(text, (list, tuple)) else text
        if status == "info" or status is None:
            wandb.termlog(text)
        elif status == "warn":
            wandb.termwarn(text)
        elif status == "error":
            wandb.termerror(text)
        else:
            raise

    def progress_update(self, text: str, percentage: Optional[float] = None) -> None:
        wandb.termlog(f"{next(self._progress)} {text}", newline=False)

    def progress_close(self) -> None:
        wandb.termlog(" " * 79)

    def code(self, text: str) -> str:
        return click.style(text, bold=True)

    def name(self, text: str) -> str:
        return click.style(text, fg="yellow")

    def link(self, link: str, text: Optional[str] = None) -> str:
        return click.style(link, fg="blue", underline=True)

    def emoji(self, name: str) -> str:
        emojis = dict()
        if platform.system() != "Windows" and wandb.util.is_unicode_safe(sys.stdout):
            emojis = dict(star="⭐️", broom="🧹", rocket="🚀")

        return emojis.get(name, "")

    def status(self, text: str, failure: Optional[bool] = None) -> str:
        color = "red" if failure else "green"
        return click.style(text, fg=color)

    def files(self, text: str) -> str:
        return click.style(text, fg="magenta", bold=True)

    def grid(self, rows: List[List[str]], title: Optional[str] = None) -> str:
        max_len = max(len(row[0]) for row in rows)
        format_row = " ".join(["{:>{max_len}}", "{}" * (len(rows[0]) - 1)])
        grid = "\n".join([format_row.format(*row, max_len=max_len) for row in rows])
        if title:
            return f"{title}\n{grid}\n"
        return f"{grid}\n"

    def panel(self, columns: List[str]) -> str:
        return "\n" + "\n".join(columns)


class PrinterJupyter(_Printer):
    def __init__(self) -> None:
        super().__init__()
        self._html = True
        self._progress = ipython.jupyter_progress_bar()

    def _display(
        self, text: Union[str, List[str], Tuple[str]], *, status: Optional[str] = None
    ) -> None:
        text = "<br/>".join(text) if isinstance(text, (list, tuple)) else text
        if status == "info" or status is None:
            ipython.display_html(text)
        elif status == "warn":
            ipython.display_html(text)
        elif status == "error":
            ipython.display_html(text)
        else:
            raise

    def code(self, text: str) -> str:
        return f"<code>{text}<code>"

    def name(self, text: str) -> str:
        return f'<strong style="color:#cdcd00">{text}</strong>'

    def link(self, link: str, text: Optional[str] = None) -> str:
        return f'<a href="{link}" target="_blank">{text or link}</a>'

    def emoji(self, name: str) -> str:
        return ""

    def status(self, text: str, failure: Optional[bool] = None) -> str:
        color = "red" if failure else "green"
        return f'<strong style="color:{color}">{text}</strong>'

    def files(self, text: str) -> str:
        return f"<code>{text}</code>"

    def progress_update(self, text: str, percent_done: float) -> None:
        if self._progress:
            self._progress.update(percent_done, text)

    def progress_close(self) -> None:
        if self._progress:
            self._progress.close()

    def grid(self, rows: List[List[str]], title: Optional[str] = None) -> str:

        format_row = "".join(["<tr>", "<td>{}</td>" * len(rows[0]), "</tr>"])
        grid = "".join([format_row.format(*row) for row in rows])
        grid = f'<table class="wandb">{grid}</table>'
        if title:
            return f"<h3>{title}</h3><br/>{grid}<br/>"
        return f"{grid}<br/>"

    def panel(self, columns: List[str]) -> str:
        row = "".join([f'<div class="wandb-col">{col}</div>' for col in columns])
        return f'{ipython.TABLE_STYLES}<div class="wandb-row">{row}</div>'


def get_printer(_jupyter: Optional[bool] = None) -> Union[PrinterTerm, PrinterJupyter]:
    if _jupyter and ipython.in_jupyter():
        return PrinterJupyter()
    return PrinterTerm()
