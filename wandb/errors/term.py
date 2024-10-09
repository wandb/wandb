"""Global functions for printing to stderr for wandb."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Protocol

import click

if TYPE_CHECKING:
    import wandb

LOG_STRING = click.style("wandb", fg="blue", bold=True)
LOG_STRING_NOCOLOR = "wandb"
ERROR_STRING = click.style("ERROR", bg="red", fg="green")
WARN_STRING = click.style("WARNING", fg="yellow")
PRINTED_MESSAGES: set[str] = set()

_silent: bool = False
"""If true, _logger is used instead of printing to stderr."""

_logger: SupportsLeveledLogging | None = None
"""A fallback logger for _silent mode."""

_show_info: bool = True
"""If false, then termlog() uses silent mode (see _silent)."""

_show_warnings: bool = True
"""If false, then termwarn() uses silent mode (see _silent)."""

_show_errors: bool = True
"""If false, then termerror() uses silent mode (see _silent)."""


class SupportsLeveledLogging(Protocol):
    """Portion of the standard logging.Logger used in this module."""

    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def termsetup(
    settings: wandb.Settings,
    logger: SupportsLeveledLogging | None,
) -> None:
    """Configures the global logging functions.

    Args:
        settings: The settings object passed to wandb.setup() or wandb.init().
        logger: A fallback logger to use for "silent" mode. In this mode,
            the logger is used instead of printing to stderr.
    """
    global _silent, _show_info, _show_warnings, _show_errors, _logger
    _silent = settings.silent
    _show_info = settings.show_info
    _show_warnings = settings.show_warnings
    _show_errors = settings.show_errors
    _logger = logger


def termlog(
    string: str = "",
    newline: bool = True,
    repeat: bool = True,
    prefix: bool = True,
) -> None:
    r"""Log an informational message to stderr.

    The message may contain ANSI color sequences and the \n character.
    Colors are stripped if stderr is not a TTY.

    Args:
        string: The message to display.
        newline: Whether to add a newline to the end of the string.
        repeat: If false, then the string is not printed if an exact match has
            already been printed through any of the other logging functions
            in this file.
        prefix: Whether to include the 'wandb:' prefix.
    """
    _log(
        string,
        newline=newline,
        repeat=repeat,
        prefix=prefix,
        silent=not _show_info,
    )


def termwarn(
    string: str,
    newline: bool = True,
    repeat: bool = True,
    prefix: bool = True,
) -> None:
    """Log a warning to stderr.

    The arguments are the same as for `termlog()`.
    """
    string = "\n".join([f"{WARN_STRING} {s}" for s in string.split("\n")])
    _log(
        string,
        newline=newline,
        repeat=repeat,
        prefix=prefix,
        silent=not _show_warnings,
        level=logging.WARNING,
    )


def termerror(
    string: str,
    newline: bool = True,
    repeat: bool = True,
    prefix: bool = True,
) -> None:
    """Log an error to stderr.

    The arguments are the same as for `termlog()`.
    """
    string = "\n".join([f"{ERROR_STRING} {s}" for s in string.split("\n")])
    _log(
        string,
        newline=newline,
        repeat=repeat,
        prefix=prefix,
        silent=not _show_errors,
        level=logging.ERROR,
    )


def _log(
    string="",
    newline=True,
    repeat=True,
    prefix=True,
    silent=False,
    level=logging.INFO,
):
    if not repeat:
        if string in PRINTED_MESSAGES:
            return

        if len(PRINTED_MESSAGES) < 1000:
            PRINTED_MESSAGES.add(string)

    if prefix:
        string = "\n".join([f"{LOG_STRING}: {s}" for s in string.split("\n")])

    silent = silent or _silent
    if not silent:
        click.echo(string, file=sys.stderr, nl=newline)
    elif not _logger:
        pass  # No fallback logger, so nothing to do.
    elif level == logging.ERROR:
        _logger.error(click.unstyle(string))
    elif level == logging.WARNING:
        _logger.warning(click.unstyle(string))
    else:
        _logger.info(click.unstyle(string))
