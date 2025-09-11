"""Terminal, Jupyter and file output for W&B."""

from __future__ import annotations

import abc
import contextlib
import itertools
import platform
import sys
from typing import Callable, Iterator

import click
from typing_extensions import override

import wandb
import wandb.util
from wandb.errors import term
from wandb.sdk import wandb_setup

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

_PROGRESS_SYMBOL_ANIMATION = "⢿⣻⣽⣾⣷⣯⣟⡿"
"""Sequence of characters for a progress spinner.

Unicode characters from the Braille Patterns block arranged
to form a subtle clockwise spinning animation.
"""

_PROGRESS_SYMBOL_COLOR = 0xB2
"""Color from the 256-color palette for the progress symbol."""

_JUPYTER_TABLE_STYLES = """
    <style>
        table.wandb td:nth-child(1) {
            padding: 0 10px;
            text-align: left;
            width: auto;
        }

        table.wandb td:nth-child(2) {
            text-align: left;
            width: 100%;
        }
    </style>
"""

_JUPYTER_PANEL_STYLES = """
    <style>
        .wandb-row {
            display: flex;
            flex-direction: row;
            flex-wrap: wrap;
            justify-content: flex-start;
            width: 100%;
        }
        .wandb-col {
            display: flex;
            flex-direction: column;
            flex-basis: 100%;
            flex: 1;
            padding: 10px;
        }
    </style>
"""


def new_printer(settings: wandb.Settings | None = None) -> Printer:
    """Returns a printer appropriate for the environment we're in.

    Args:
        settings: The settings of a run. If not provided and `wandb.setup()`
            has been called, then global settings are used. Otherwise,
            settings (such as silent mode) are ignored.
    """
    if not settings and (s := wandb_setup.singleton().settings_if_loaded):
        settings = s

    if ipython.in_jupyter():
        return _PrinterJupyter(settings=settings)
    else:
        return _PrinterTerm(settings=settings)


class Printer(abc.ABC):
    """An object that shows styled text to the user."""

    @contextlib.contextmanager
    @abc.abstractmethod
    def dynamic_text(self) -> Iterator[DynamicText | None]:
        """A context manager providing a handle to a block of changeable text.

        Since `wandb` may be outputting to a terminal, it's important to only
        use this when `wandb` is performing blocking calls, or else text output
        by non-`wandb` code may get overwritten.

        Returns None if dynamic text is not supported, such as if stderr is not
        a TTY and we're not in a Jupyter notebook.
        """

    @abc.abstractmethod
    def display(
        self,
        text: str | list[str] | tuple[str],
        *,
        level: str | int | None = None,
    ) -> None:
        """Display text to the user.

        Args:
            text: The text to display. If given an iterable of strings, they're
                joined with newlines.
            level: The logging level, for controlling verbosity.
        """

    @abc.abstractmethod
    def progress_update(
        self,
        text: str,
        percent_done: float | None = None,
    ) -> None:
        r"""Set the text on the progress indicator.

        Args:
            text: The text to set, which must end with \r.
            percent_done: The current progress, between 0 and 1.
        """

    @abc.abstractmethod
    def progress_close(self) -> None:
        """Close the progress indicator.

        After this, `progress_update` should not be used.
        """

    @staticmethod
    def _sanitize_level(name_or_level: str | int | None) -> int:
        """Returns the number corresponding to the logging level.

        Args:
            name_or_level: The logging level passed to `display`.

        Raises:
            ValueError: if the input is not a valid logging level.
        """
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

    @property
    @abc.abstractmethod
    def supports_html(self) -> bool:
        """Whether text passed to display may contain HTML styling."""

    @property
    @abc.abstractmethod
    def supports_unicode(self) -> bool:
        """Whether text passed to display may contain arbitrary Unicode."""

    def sparklines(self, series: list[int | float]) -> str | None:
        """Returns a Unicode art representation of the series of numbers.

        Also known as "ASCII art", except this uses non-ASCII
        Unicode characters.

        Returns None if the output doesn't support Unicode.
        """
        if self.supports_unicode:
            return sparkline.sparkify(series)
        else:
            return None

    @abc.abstractmethod
    def code(self, text: str) -> str:
        """Returns the text styled like code."""

    @abc.abstractmethod
    def name(self, text: str) -> str:
        """Returns the text styled like a run name."""

    @abc.abstractmethod
    def link(self, link: str, text: str | None = None) -> str:
        """Returns the text styled like a link.

        Args:
            link: The target link.
            text: The text to show for the link. If not set, or if we're not
                in an environment that supports clickable links,
                this is ignored.
        """

    @abc.abstractmethod
    def secondary_text(self, text: str) -> str:
        """Returns the text styled to draw less attention."""

    @abc.abstractmethod
    def loading_symbol(self, tick: int) -> str:
        """Returns a frame of an animated loading symbol.

        May return an empty string.

        Args:
            tick: An index into the animation.
        """

    @abc.abstractmethod
    def error(self, text: str) -> str:
        """Returns the text colored like an error."""

    @abc.abstractmethod
    def emoji(self, name: str) -> str:
        """Returns the string for a named emoji, or an empty string."""

    @abc.abstractmethod
    def files(self, text: str) -> str:
        """Returns the text styled like a file path."""

    @abc.abstractmethod
    def grid(self, rows: list[list[str]], title: str | None = None) -> str:
        """Returns a grid of strings with an optional title."""

    @abc.abstractmethod
    def panel(self, columns: list[str]) -> str:
        """Returns the column text combined in a compact way."""


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


class _PrinterTerm(Printer):
    def __init__(self, *, settings: wandb.Settings | None) -> None:
        super().__init__()
        self._settings = settings
        self._progress = itertools.cycle(["-", "\\", "|", "/"])

    @override
    @contextlib.contextmanager
    def dynamic_text(self) -> Iterator[DynamicText | None]:
        if self._settings and self._settings.silent:
            yield None
            return

        with term.dynamic_text() as handle:
            if not handle:
                yield None
            else:
                yield _DynamicTermText(handle)

    @override
    def display(
        self,
        text: str | list[str] | tuple[str],
        *,
        level: str | int | None = None,
    ) -> None:
        if self._settings and self._settings.silent:
            return

        text = "\n".join(text) if isinstance(text, (list, tuple)) else text
        self._display_fn_mapping(level)(text)

    @staticmethod
    def _display_fn_mapping(level: str | int | None = None) -> Callable[[str], None]:
        level = Printer._sanitize_level(level)

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

    @override
    def progress_update(self, text: str, percent_done: float | None = None) -> None:
        if self._settings and self._settings.silent:
            return

        wandb.termlog(f"{next(self._progress)} {text}", newline=False)

    @override
    def progress_close(self) -> None:
        if self._settings and self._settings.silent:
            return

    @property
    @override
    def supports_html(self) -> bool:
        return False

    @property
    @override
    def supports_unicode(self) -> bool:
        return wandb.util.is_unicode_safe(sys.stderr)

    @override
    def code(self, text: str) -> str:
        ret: str = click.style(text, bold=True)
        return ret

    @override
    def name(self, text: str) -> str:
        ret: str = click.style(text, fg="yellow")
        return ret

    @override
    def link(self, link: str, text: str | None = None) -> str:
        ret: str = click.style(link, fg="blue", underline=True)
        # ret = f"\x1b[m{text or link}\x1b[0m"
        # ret = f"\x1b]8;;{link}\x1b\\{ret}\x1b]8;;\x1b\\"
        return ret

    @override
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

    @override
    def secondary_text(self, text: str) -> str:
        # NOTE: "white" is really a light gray, and is usually distinct
        #   from the terminal's foreground color (i.e. default text color)
        return click.style(text, fg="white")

    @override
    def loading_symbol(self, tick: int) -> str:
        if not self.supports_unicode:
            return ""

        idx = tick % len(_PROGRESS_SYMBOL_ANIMATION)
        return click.style(
            _PROGRESS_SYMBOL_ANIMATION[idx],
            fg=_PROGRESS_SYMBOL_COLOR,
        )

    @override
    def error(self, text: str) -> str:
        return click.style(text, fg="red")

    @override
    def files(self, text: str) -> str:
        ret: str = click.style(text, fg="magenta", bold=True)
        return ret

    @override
    def grid(self, rows: list[list[str]], title: str | None = None) -> str:
        max_len = max(len(row[0]) for row in rows)
        format_row = " ".join(["{:>{max_len}}", "{}" * (len(rows[0]) - 1)])
        grid = "\n".join([format_row.format(*row, max_len=max_len) for row in rows])
        if title:
            return f"{title}\n{grid}\n"
        return f"{grid}\n"

    @override
    def panel(self, columns: list[str]) -> str:
        return "\n" + "\n".join(columns)


class _DynamicTermText(DynamicText):
    def __init__(self, handle: term.DynamicBlock) -> None:
        self._handle = handle

    @override
    def set_text(self, text: str) -> None:
        self._handle.set_text(text)


class _PrinterJupyter(Printer):
    def __init__(self, *, settings: wandb.Settings | None) -> None:
        super().__init__()
        self._settings = settings
        self._progress = ipython.jupyter_progress_bar()

        from IPython import display

        self._ipython_display = display

    @override
    @contextlib.contextmanager
    def dynamic_text(self) -> Iterator[DynamicText | None]:
        if self._settings and self._settings.silent:
            yield None
            return

        handle = self._ipython_display.display(
            self._ipython_display.HTML(""),
            display_id=True,
        )

        if not handle:
            yield None
            return

        try:
            yield _DynamicJupyterText(handle)
        finally:
            handle.update(self._ipython_display.HTML(""))

    @override
    def display(
        self,
        text: str | list[str] | tuple[str],
        *,
        level: str | int | None = None,
    ) -> None:
        if self._settings and self._settings.silent:
            return

        text = "<br>".join(text) if isinstance(text, (list, tuple)) else text
        text = "<br>".join(text.splitlines())
        self._ipython_display.display(self._ipython_display.HTML(text))

    @property
    @override
    def supports_html(self) -> bool:
        return True

    @property
    @override
    def supports_unicode(self) -> bool:
        return True

    @override
    def code(self, text: str) -> str:
        return f"<code>{text}<code>"

    @override
    def name(self, text: str) -> str:
        return f'<strong style="color:#cdcd00">{text}</strong>'

    @override
    def link(self, link: str, text: str | None = None) -> str:
        return f'<a href={link!r} target="_blank">{text or link}</a>'

    @override
    def emoji(self, name: str) -> str:
        return ""

    @override
    def secondary_text(self, text: str) -> str:
        return text

    @override
    def loading_symbol(self, tick: int) -> str:
        return ""

    @override
    def error(self, text: str) -> str:
        return f'<strong style="color:red">{text}</strong>'

    @override
    def files(self, text: str) -> str:
        return f"<code>{text}</code>"

    @override
    def progress_update(
        self,
        text: str,
        percent_done: float | None = None,
    ) -> None:
        if (self._settings and self._settings.silent) or not self._progress:
            return

        if percent_done is None:
            percent_done = 1.0

        self._progress.update(percent_done, text)

    @override
    def progress_close(self) -> None:
        if self._progress:
            self._progress.close()

    @override
    def grid(self, rows: list[list[str]], title: str | None = None) -> str:
        format_row = "".join(["<tr>", "<td>{}</td>" * len(rows[0]), "</tr>"])
        grid = "".join([format_row.format(*row) for row in rows])
        grid = f'<table class="wandb">{grid}</table>'
        if title:
            return f"<h3>{title}</h3><br/>{grid}<br/>"
        return f"{_JUPYTER_TABLE_STYLES}{grid}<br/>"

    @override
    def panel(self, columns: list[str]) -> str:
        row = "".join([f'<div class="wandb-col">{col}</div>' for col in columns])
        return f'{_JUPYTER_PANEL_STYLES}<div class="wandb-row">{row}</div>'


class _DynamicJupyterText(DynamicText):
    def __init__(self, handle) -> None:
        from IPython import display

        self._ipython_to_html = display.HTML
        self._handle: display.DisplayHandle = handle

    @override
    def set_text(self, text: str) -> None:
        text = "<br>".join(text.splitlines())
        self._handle.update(self._ipython_to_html(text))
