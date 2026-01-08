"""Global functions for interacting with the terminal for wandb.

The functions termlog, termwarn and termerror print to stderr.

The function terminput prints to stderr and reads from stdin.

We print to stderr because wandb does not output any messages that are useful
to pipe to another program. Using stderr allows using wandb in a program that
*does* output pipe-able text.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import sys
import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol

import click

if TYPE_CHECKING:
    import wandb

LOG_STRING = click.style("wandb", fg="blue", bold=True)
LOG_STRING_NOCOLOR = "wandb"
ERROR_STRING = click.style("ERROR", bg="red", fg="green")
WARN_STRING = click.style("WARNING", fg="yellow")

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


_printed_messages: set[str] = set()
"""Messages logged with repeat=False."""

_dynamic_text_lock = threading.Lock()
"""Lock held for dynamic text operations.

All uses of `_dynamic_blocks` and calls to functions that start with
the `_l_` prefix must be guarded by this lock.
"""

_dynamic_blocks: list[DynamicBlock] = []
"""Active dynamic text areas, created with dynamic_text()."""


class NotATerminalError(Exception):
    """The output device is not sufficiently capable for the operation."""


class SupportsLeveledLogging(Protocol):
    """Portion of the standard logging.Logger used in this module."""

    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def termsetup(
    settings: wandb.Settings,
    logger: SupportsLeveledLogging | None,
) -> None:
    """Configure the global logging functions.

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


@contextlib.contextmanager
def dynamic_text() -> Iterator[DynamicBlock | None]:
    """A context manager that provides a handle to a new dynamic text area.

    The text goes to stderr. Returns None if dynamic text is not supported.

    Dynamic text must only be used while `wandb` has control of the terminal,
    or else text written by other programs will be overwritten. It's
    appropriate to use during a blocking operation.

    ```
    with term.dynamic_text() as text_area:
        if text_area:
            text_area.set_text("Writing to a terminal.")
            for i in range(2000):
                text_area.set_text(f"Still going... ({i}/2000)")
                time.sleep(0.001)
        else:
            wandb.termlog("Writing to a file or dumb terminal.")
            time.sleep(1)
            wandb.termlog("Finished 1000/2000 tasks, still working...")
            time.sleep(1)
    wandb.termlog("Done!", err=True)
    ```
    """
    # For now, dynamic text always corresponds to the "INFO" level.
    if _silent or not _show_info:
        yield None
        return

    # NOTE: In Jupyter notebooks, this will return False. Notebooks
    #   support ANSI color sequences and the '\r' character, but not
    #   cursor motions or line clear commands.
    if not _sys_stderr_isatty() or _is_term_dumb():
        yield None
        return

    # NOTE: On Windows < 10, ANSI escape sequences such as \x1b[Am and \x1b[2K,
    #   used to move the cursor and clear text, aren't supported by the built-in
    #   console. However, we rely on the click library's use of colorama which
    #   emulates support for such sequences.
    #
    #   For this reason, we don't have special checks for Windows.

    block = DynamicBlock()

    with _dynamic_text_lock:
        _dynamic_blocks.append(block)

    try:
        yield block
    finally:
        with _dynamic_text_lock:
            block._lines_to_print = []
            _l_rerender_dynamic_blocks()
            _dynamic_blocks.remove(block)


def _sys_stderr_isatty() -> bool:
    """Returns sys.stderr.isatty().

    Defined here for patching in tests.
    """
    return _isatty(sys.stderr)


def _sys_stdin_isatty() -> bool:
    """Returns sys.stdin.isatty().

    Defined here for patching in tests.
    """
    return _isatty(sys.stdin)


def _isatty(stream: object) -> bool:
    """Returns true if the stream defines isatty and returns true for it.

    This is needed because some people patch `sys.stderr` / `sys.stdin`
    with incompatible objects, e.g. a Logger.

    Args:
        stream: An IO object like stdin or stderr.
    """
    isatty = getattr(stream, "isatty", None)

    if not isatty or not callable(isatty):
        return False

    try:
        return bool(isatty())
    except TypeError:  # if isatty has required arguments
        return False


def _is_term_dumb() -> bool:
    """Returns whether the TERM environment variable is set to 'dumb'.

    This is a convention to indicate that the terminal doesn't support
    ANSI sequences like colors, clearing the screen and positioning the cursor.
    """
    return os.getenv("TERM") == "dumb"


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


def _in_jupyter() -> bool:
    """Returns True if we're in a Jupyter notebook."""
    # Lazy import to avoid circular imports.
    from wandb.sdk.lib import ipython

    return ipython.in_jupyter()


def can_use_terminput() -> bool:
    """Returns True if terminput won't raise a NotATerminalError."""
    if _silent or not _show_info or _is_term_dumb():
        return False

    from wandb import util

    # TODO: Verify the databricks check is still necessary.
    # Originally added to fix WB-5264.
    if util._is_databricks():
        return False

    # isatty() returns false in Jupyter, but it's OK to output ANSI color
    # sequences and to read from stdin.
    return _in_jupyter() or (_sys_stderr_isatty() and _sys_stdin_isatty())


def terminput(
    prompt: str,
    *,
    timeout: float | None = None,
    hide: bool = False,
) -> str:
    """Prompt the user for input.

    Args:
        prompt: The prompt to display. The prompt is printed without a newline
            and the cursor is positioned after the prompt's last character.
            The prompt should end with whitespace.
        timeout: A timeout after which to raise a TimeoutError.
            Cannot be set if hide is True.
        hide: If true, does not echo the characters typed by the user.
            This is useful for passwords.

    Returns:
        The text typed by the user before pressing the 'return' key.

    Raises:
        TimeoutError: If a timeout was specified and expired.
        NotATerminalError: If the output device is not capable, like if stderr
            is redirected to a file, stdin is a pipe or closed, TERM=dumb is
            set, or wandb is configured in 'silent' mode.
        KeyboardInterrupt: If the user pressed Ctrl+C during the prompt.
    """
    prefixed_prompt = f"{LOG_STRING}: {prompt}"
    return _terminput(prefixed_prompt, timeout=timeout, hide=hide)


def confirm(prompt: str) -> bool:
    """Prompt the user with a yes/no question.

    Args:
        prompt: A prompt ending with a question mark (not whitespace),
            like "Are you sure?".

    Returns:
        The user's choice.
    """
    prompt = f"{prompt} [y/n] "
    while True:
        answer = terminput(prompt).strip().lower()

        if answer in ("n", "no"):
            return False
        if answer in ("y", "yes"):
            return True


def _terminput(
    prefixed_prompt: str,
    *,
    timeout: float | None = None,
    hide: bool = False,
) -> str:
    """Implements terminput() and can be patched by tests."""
    if not can_use_terminput():
        raise NotATerminalError

    if hide and timeout is not None:
        # Only click.prompt() can hide, and only timed_input can time out.
        raise NotImplementedError

    if timeout is not None:
        # Lazy import to avoid circular imports.
        from wandb.sdk.lib.timed_input import timed_input

        try:
            return timed_input(
                prefixed_prompt,
                timeout=timeout,
                err=True,
                jupyter=_in_jupyter(),
            )
        except KeyboardInterrupt:
            sys.stderr.write("\n")
            raise

    try:
        return click.prompt(
            prefixed_prompt,
            prompt_suffix="",
            hide_input=hide,
            err=True,
        )
    except click.Abort:
        sys.stderr.write("\n")
        raise KeyboardInterrupt from None


class DynamicBlock:
    """A handle to a changeable text area in the terminal."""

    def __init__(self) -> None:
        self._lines_to_print: list[str] = []
        self._num_lines_printed = 0

    def set_text(self, text: str, prefix: bool = True) -> None:
        r"""Replace the text in this block.

        Args:
            text: The text to put in the block, with lines separated
                by \n characters. The text should not end in \n unless
                a blank line at the end of the block is desired.
            prefix: Whether to include the "wandb:" prefix.
        """
        with _dynamic_text_lock:
            self._lines_to_print = text.splitlines()

            if prefix:
                self._lines_to_print = [
                    f"{LOG_STRING}: {line}" for line in self._lines_to_print
                ]

            _l_rerender_dynamic_blocks()

    def _l_clear(self) -> None:
        """Send terminal commands to clear all previously printed lines.

        The lock must be held, and the cursor must be on the line after this
        block of text.
        """
        # NOTE: We rely on the fact that click.echo() uses colorama which
        #   emulates these ANSI sequences on older Windows versions.
        #
        # \r       move cursor to start of line
        # \x1b[Am  move cursor up
        # \x1b[2K  delete line (sometimes moves cursor)
        # \r       move cursor to start of line
        move_up_and_delete_line = "\r\x1b[Am\x1b[2K\r"
        click.echo(
            move_up_and_delete_line * self._num_lines_printed,
            file=sys.stderr,
            nl=False,
        )
        self._num_lines_printed = 0

    def _l_print(self) -> None:
        """Print out this block of text.

        The lock must be held.
        """
        if self._lines_to_print:
            # Trim lines before printing. This is crucial because the \x1b[Am
            # (cursor up) sequence used when clearing the text moves up by one
            # visual line, and the terminal may be wrapping long lines onto
            # multiple visual lines.
            #
            # There is no ANSI escape sequence that moves the cursor up by one
            # "physical" line instead. Note that the user may resize their
            # terminal.
            term_width = _shutil_get_terminal_width()
            click.echo(
                "\n".join(
                    _ansi_shorten(line, term_width)  #
                    for line in self._lines_to_print
                ),
                file=sys.stderr,
            )

        self._num_lines_printed += len(self._lines_to_print)


def _shutil_get_terminal_width() -> int:
    """Returns the width of the terminal.

    Defined here for patching in tests.
    """
    columns, _ = shutil.get_terminal_size()
    return columns


_ANSI_RE = re.compile("\x1b\\[(K|.*?m)")


def _ansi_shorten(text: str, width: int) -> str:
    """Shorten text potentially containing ANSI sequences to fit a width."""
    first_ansi = _ANSI_RE.search(text)

    if not first_ansi:
        return _raw_shorten(text, width)

    if first_ansi.start() > width - 3:
        return _raw_shorten(text[: first_ansi.start()], width)

    return text[: first_ansi.end()] + _ansi_shorten(
        text[first_ansi.end() :],
        # Key part: the ANSI sequence doesn't reduce the remaining width.
        width - first_ansi.start(),
    )


def _raw_shorten(text: str, width: int) -> str:
    """Shorten text to fit a width, replacing the end with "...".

    Unlike textwrap.shorten(), this does not drop whitespace or do anything
    smart.
    """
    if len(text) <= width:
        return text

    return text[: width - 3] + "..."


def _log(
    string: str = "",
    newline: bool = True,
    repeat: bool = True,
    prefix: bool = True,
    silent: bool = False,
    level: int = logging.INFO,
) -> None:
    with _dynamic_text_lock, _l_above_dynamic_text():
        if not repeat:
            if string in _printed_messages:
                return

            if len(_printed_messages) < 1000:
                _printed_messages.add(string)

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


def _l_rerender_dynamic_blocks() -> None:
    """Clear and re-print all dynamic text.

    The lock must be held. The cursor must be positioned at the start of
    the first line after the dynamic text area.
    """
    with _l_above_dynamic_text():
        # We just want the side-effect of rerendering the dynamic text.
        pass


@contextlib.contextmanager
def _l_above_dynamic_text():
    """A context manager for inserting static text above any dynamic text.

    The lock must be held. The cursor must be positioned at the start of the
    first line after the dynamic text area.

    The dynamic text is re-rendered.
    """
    _l_clear_dynamic_blocks()

    try:
        yield
    finally:
        _l_print_dynamic_blocks()


def _l_clear_dynamic_blocks() -> None:
    """Delete all dynamic text.

    The lock must be held, and the cursor must be positioned at the start
    of the first line after the dynamic text area. After this, the cursor
    is positioned at the start of the first line after all static text.
    """
    for block in reversed(_dynamic_blocks):
        block._l_clear()


def _l_print_dynamic_blocks() -> None:
    """Output all dynamic text.

    The lock must be held. After this, the cursor is positioned at the start
    of the first line after the dynamic text area.
    """
    for block in _dynamic_blocks:
        block._l_print()
