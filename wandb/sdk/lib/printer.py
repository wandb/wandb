# Note: this is a helper printer class, this file might go away once we switch to rich console printing

import abc
import itertools
import platform
import sys
from typing import Callable, List, Optional, Tuple, Union

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

import click

import wandb
from wandb.errors import term

from . import ipython, sparkline

# Follow the same logic as the python logging module
CRITICAL = 50
FATAL = CRITICAL
ERROR = 40
WARNING = 30
WARN = WARNING
INFO = 20
DEBUG = 10
NOTSET = 0

_level_to_name = {
    CRITICAL: "CRITICAL",
    ERROR: "ERROR",
    WARNING: "WARNING",
    INFO: "INFO",
    DEBUG: "DEBUG",
    NOTSET: "NOTSET",
}

_name_to_level = {
    "CRITICAL": CRITICAL,
    "FATAL": FATAL,
    "ERROR": ERROR,
    "WARN": WARNING,
    "WARNING": WARNING,
    "INFO": INFO,
    "DEBUG": DEBUG,
    "NOTSET": NOTSET,
}


class _Printer(abc.ABC):
    def sparklines(self, series: List[Union[int, float]]) -> Optional[str]:
        # Only print sparklines if the terminal is utf-8
        if wandb.util.is_unicode_safe(sys.stdout):
            return sparkline.sparkify(series)
        return None

    def abort(
        self,
    ) -> str:
        return "Control-C" if platform.system() != "Windows" else "Ctrl-C"

    @abc.abstractmethod
    def dynamic_text(self) -> "Optional[DynamicText]":
        """Returns a handle to a new block of changeable text.

        Since `wandb` may be outputting to a terminal, it's important to only
        use this when `wandb` is performing blocking calls, or else text output
        by non-`wandb` code may get overwritten.

        Returns None if dynamic text is not supported, such as if stderr is not
        a TTY.
        """

    def display(
        self,
        text: Union[str, List[str], Tuple[str]],
        *,
        level: Optional[Union[str, int]] = None,
        off: Optional[bool] = None,
        default_text: Optional[Union[str, List[str], Tuple[str]]] = None,
    ) -> None:
        if off:
            return
        self._display(text, level=level, default_text=default_text)

    @abc.abstractmethod
    def _display(
        self,
        text: Union[str, List[str], Tuple[str]],
        *,
        level: Optional[Union[str, int]] = None,
        default_text: Optional[Union[str, List[str], Tuple[str]]] = None,
    ) -> None: ...

    @staticmethod
    def _sanitize_level(name_or_level: Optional[Union[str, int]]) -> int:
        if isinstance(name_or_level, str):
            try:
                return _name_to_level[name_or_level.upper()]
            except KeyError:
                raise ValueError(
                    f"Unknown level name: {name_or_level}, supported levels: {_name_to_level.keys()}"
                )

        if isinstance(name_or_level, int):
            return name_or_level

        if name_or_level is None:
            return INFO

        raise ValueError(f"Unknown status level {name_or_level}")

    @abc.abstractmethod
    def code(self, text: str) -> str: ...

    @abc.abstractmethod
    def name(self, text: str) -> str: ...

    @abc.abstractmethod
    def link(self, link: str, text: Optional[str] = None) -> str: ...

    @abc.abstractmethod
    def emoji(self, name: str) -> str: ...

    @abc.abstractmethod
    def status(self, text: str, failure: Optional[bool] = None) -> str: ...

    @abc.abstractmethod
    def files(self, text: str) -> str: ...

    @abc.abstractmethod
    def grid(self, rows: List[List[str]], title: Optional[str] = None) -> str: ...

    @abc.abstractmethod
    def panel(self, columns: List[str]) -> str: ...


class DynamicText(abc.ABC):
    """A handle to a block of text that's allowed to change."""

    @abc.abstractmethod
    def set_text(self, text: str) -> None:
        r"""Change the text.

        Args:
            text: The text to put in the block, with lines separated
                by \n characters. The text should not end in \n unless
                a blank line at the end of the block is desired.
                May include styled output from methods on the Printer
                that created this.
        """

    @abc.abstractmethod
    def remove(self) -> None:
        """Remove the text.

        Further updates are ignored.
        """


class PrinterTerm(_Printer):
    def __init__(self) -> None:
        super().__init__()
        self._html = False
        self._progress = itertools.cycle(["-", "\\", "|", "/"])

    @override
    def dynamic_text(self) -> DynamicText | None:
        handle = term.dynamic_text()

        if not handle:
            return None

        return _DynamicTermText(handle)

    def _display(
        self,
        text: Union[str, List[str], Tuple[str]],
        *,
        level: Optional[Union[str, int]] = None,
        default_text: Optional[Union[str, List[str], Tuple[str]]] = None,
    ) -> None:
        text = "\n".join(text) if isinstance(text, (list, tuple)) else text
        if default_text is not None:
            default_text = (
                "\n".join(default_text)
                if isinstance(default_text, (list, tuple))
                else default_text
            )
            text = text or default_text
        self._display_fn_mapping(level)(text)

    @staticmethod
    def _display_fn_mapping(level: Optional[Union[str, int]]) -> Callable[[str], None]:
        level = _Printer._sanitize_level(level)

        if level >= CRITICAL:
            return wandb.termerror
        elif ERROR <= level < CRITICAL:
            return wandb.termerror
        elif WARNING <= level < ERROR:
            return wandb.termwarn
        elif INFO <= level < WARNING:
            return wandb.termlog
        elif DEBUG <= level < INFO:
            return wandb.termlog
        else:
            return wandb.termlog

    def progress_update(self, text: str, percent_done: Optional[float] = None) -> None:
        wandb.termlog(f"{next(self._progress)} {text}", newline=False)

    def progress_close(self, text: Optional[str] = None) -> None:
        text = text or " " * 79
        wandb.termlog(text)

    def code(self, text: str) -> str:
        ret: str = click.style(text, bold=True)
        return ret

    def name(self, text: str) -> str:
        ret: str = click.style(text, fg="yellow")
        return ret

    def link(self, link: str, text: Optional[str] = None) -> str:
        ret: str = click.style(link, fg="blue", underline=True)
        # ret = f"\x1b[m{text or link}\x1b[0m"
        # ret = f"\x1b]8;;{link}\x1b\\{ret}\x1b]8;;\x1b\\"
        return ret

    def emoji(self, name: str) -> str:
        emojis = dict()
        if platform.system() != "Windows" and wandb.util.is_unicode_safe(sys.stdout):
            emojis = dict(
                star="⭐️",
                broom="🧹",
                rocket="🚀",
                gorilla="🦍",
                turtle="🐢",
                lightning="️⚡",
            )

        return emojis.get(name, "")

    def status(self, text: str, failure: Optional[bool] = None) -> str:
        color = "red" if failure else "green"
        ret: str = click.style(text, fg=color)
        return ret

    def files(self, text: str) -> str:
        ret: str = click.style(text, fg="magenta", bold=True)
        return ret

    def grid(self, rows: List[List[str]], title: Optional[str] = None) -> str:
        max_len = max(len(row[0]) for row in rows)
        format_row = " ".join(["{:>{max_len}}", "{}" * (len(rows[0]) - 1)])
        grid = "\n".join([format_row.format(*row, max_len=max_len) for row in rows])
        if title:
            return f"{title}\n{grid}\n"
        return f"{grid}\n"

    def panel(self, columns: List[str]) -> str:
        return "\n" + "\n".join(columns)


class _DynamicTermText(DynamicText):
    def __init__(self, handle: term.DynamicBlock) -> None:
        self._handle = handle

    @override
    def set_text(self, text: str) -> None:
        self._handle.set_text(text)

    @override
    def remove(self) -> None:
        self._handle.remove()


class PrinterJupyter(_Printer):
    def __init__(self) -> None:
        super().__init__()
        self._html = True
        self._progress = ipython.jupyter_progress_bar()

    @override
    def dynamic_text(self) -> DynamicText | None:
        # TODO: Support dynamic text in Jupyter notebooks.
        return None

    def _display(
        self,
        text: Union[str, List[str], Tuple[str]],
        *,
        level: Optional[Union[str, int]] = None,
        default_text: Optional[Union[str, List[str], Tuple[str]]] = None,
    ) -> None:
        text = "<br/>".join(text) if isinstance(text, (list, tuple)) else text
        if default_text is not None:
            default_text = (
                "<br/>".join(default_text)
                if isinstance(default_text, (list, tuple))
                else default_text
            )
            text = text or default_text
        self._display_fn_mapping(level)(text)

    @staticmethod
    def _display_fn_mapping(level: Optional[Union[str, int]]) -> Callable[[str], None]:
        level = _Printer._sanitize_level(level)

        if level >= CRITICAL:
            return ipython.display_html
        elif ERROR <= level < CRITICAL:
            return ipython.display_html
        elif WARNING <= level < ERROR:
            return ipython.display_html
        elif INFO <= level < WARNING:
            return ipython.display_html
        elif DEBUG <= level < INFO:
            return ipython.display_html
        else:
            return ipython.display_html

    def code(self, text: str) -> str:
        return f"<code>{text}<code>"

    def name(self, text: str) -> str:
        return f'<strong style="color:#cdcd00">{text}</strong>'

    def link(self, link: str, text: Optional[str] = None) -> str:
        return f'<a href={link!r} target="_blank">{text or link}</a>'

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

    def progress_close(self, _: Optional[str] = None) -> None:
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


Printer = Union[PrinterTerm, PrinterJupyter]


def get_printer(_jupyter: bool) -> Printer:
    if _jupyter:
        return PrinterJupyter()
    return PrinterTerm()
