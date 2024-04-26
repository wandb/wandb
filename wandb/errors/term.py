import logging
import sys
from typing import Any

import click

LOG_STRING = click.style("wandb", fg="blue", bold=True)
LOG_STRING_NOCOLOR = "wandb"
ERROR_STRING = click.style("ERROR", bg="red", fg="green")
WARN_STRING = click.style("WARNING", fg="yellow")
PRINTED_MESSAGES = set()  # type: ignore

_silent = False
_show_info = True
_show_warnings = True
_show_errors = True
_logger = None


def termsetup(settings, logger) -> None:
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
    """Log to standard error with formatting.

    Arguments:
        string (str, optional): The string to print
        newline (bool, optional): Print a newline at the end of the string
        repeat (bool, optional): If set to False only prints the string once per process
    """
    _log(
        string=string,
        newline=newline,
        repeat=repeat,
        prefix=prefix,
        silent=not _show_info,
    )


def termwarn(string: str, **kwargs: Any) -> None:
    string = "\n".join([f"{WARN_STRING} {s}" for s in string.split("\n")])
    _log(
        string=string,
        newline=True,
        silent=not _show_warnings,
        level=logging.WARNING,
        **kwargs,
    )


def termerror(string: str, **kwargs: Any) -> None:
    string = "\n".join([f"{ERROR_STRING} {s}" for s in string.split("\n")])
    _log(
        string=string,
        newline=True,
        silent=not _show_errors,
        level=logging.ERROR,
        **kwargs,
    )


def _log(
    string="",
    newline=True,
    repeat=True,
    prefix=True,
    silent=False,
    level=logging.INFO,
):
    global _logger
    silent = silent or _silent
    if string:
        if prefix:
            line = "\n".join([f"{LOG_STRING}: {s}" for s in string.split("\n")])
        else:
            line = string
    else:
        line = ""
    if not repeat and line in PRINTED_MESSAGES:
        return
    # Repeated line tracking limited to 1k messages
    if len(PRINTED_MESSAGES) < 1000:
        PRINTED_MESSAGES.add(line)
    if silent:
        if level == logging.ERROR:
            _logger.error(line)
        elif level == logging.WARNING:
            _logger.warning(line)
        else:
            _logger.info(line)
    else:
        click.echo(line, file=sys.stderr, nl=newline)
