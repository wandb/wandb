"""Appends a scheduler's output to the sweep's controller run."""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import TracebackType
from typing import TYPE_CHECKING

from wandb.errors import term
from wandb.sdk.lib import console_capture

if TYPE_CHECKING:
    import wandb

# A partial line is flushed once it grows past this, so output that
# redraws one line in place cannot hold text back forever.
_MAX_HELD_CHARACTERS = 4096


def _decoded(write: Callable[[str], None]) -> Callable[[bytes | str, int], None]:
    """Adapt a text writer to the console capture callback signature."""

    def on_write(data: bytes | str, written: int, /) -> None:
        text = data[:written]
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        write(text)

    return on_write


def _term_function(level: int) -> Callable[[str], None]:
    """The `term` function that prints a line of the given severity."""
    if level >= logging.ERROR:
        return term.termerror
    if level >= logging.WARNING:
        return term.termwarn
    return term.termlog


class LineBuffer:
    """Assembles written text into finished lines.

    <!-- lazydoc-ignore-init: internal -->
    """

    def __init__(self) -> None:
        self._held = ""

    def take_lines(self, text: str) -> list[str]:
        """Return the lines `text` finishes, holding back a partial one.

        Args:
            text: Newly written text, which may start or end mid-line.
        """
        lines = (self._held + text).split("\n")
        self._held = lines.pop()

        if len(self._held) >= _MAX_HELD_CHARACTERS:
            lines.append(self._held)
            self._held = ""

        return [line.rstrip("\r") for line in lines]

    def take_rest(self) -> list[str]:
        """Return the held partial line, which nothing will finish."""
        rest, self._held = self._held.rstrip("\r"), ""
        return [rest] if rest else []


class ControllerRunLogger:
    """Appends this process's output to the sweep's controller run.

    Args:
        run: The sweep's controller run.

    <!-- lazydoc-ignore-init: internal -->
    """

    def __init__(self, run: wandb.Run) -> None:
        self._run = run
        self._stdout = LineBuffer()
        self._stderr = LineBuffer()
        self._uninstall: list[Callable[[], None]] = []
        self._is_closed = False

    def __enter__(self) -> ControllerRunLogger:
        self.install()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def install(self) -> None:
        """Start appending this process's console output to the run."""
        if self._uninstall:
            return

        try:
            self._uninstall = [
                console_capture.capture_stdout(_decoded(self.write_stdout)),
                console_capture.capture_stderr(_decoded(self.write_stderr)),
            ]
        except console_capture.CannotCaptureConsoleError as e:
            term.termwarn(f"Scheduler output will not reach the sweep: {e}")

    def write_stdout(self, text: str) -> None:
        """Append the lines `text` finishes on this process's stdout.

        Args:
            text: Newly written text, which may start or end mid-line.
        """
        self._write(self._stdout, text)

    def write_stderr(self, text: str) -> None:
        """Append the lines `text` finishes on this process's stderr.

        Args:
            text: Newly written text, which may start or end mid-line.
        """
        self._write(self._stderr, text)

    def log(
        self,
        message: str,
        *,
        label: str = "",
        level: int = logging.INFO,
    ) -> None:
        """Print a line and append it to the run under its own label.

        The terminal copy is hidden from console capture so that the
        line is not also appended under the scheduler's own label.

        Args:
            message: The line to log, without a trailing newline.
            label: Identifies the writer, displayed beside the line.
                Defaults to the run's label.
            level: The line's severity, as a `logging` level.
        """
        log_to_term = _term_function(level)

        with console_capture.uncaptured():
            log_to_term(message)

        # term marks the severity on the terminal but not in the text.
        # Errors carry theirs to the run as a level, so only warnings
        # have to say so themselves.
        if logging.WARNING <= level < logging.ERROR:
            message = f"WARNING {message}"

        self._append(message, label=label, is_error=level >= logging.ERROR)

    def close(self) -> None:
        """Append any unfinished line and stop capturing.

        Must run before the run is finished.
        """
        if self._is_closed:
            return

        for uninstall in self._uninstall:
            uninstall()
        self._uninstall = []

        for buffer in (self._stdout, self._stderr):
            for line in buffer.take_rest():
                self._append(line)

        self._is_closed = True

    def _write(self, buffer: LineBuffer, text: str) -> None:
        # Console capture calls its callbacks from one thread at a time,
        # so a buffer needs no lock of its own.
        for line in buffer.take_lines(text):
            self._append(line)

    def _append(
        self,
        line: str,
        *,
        label: str = "",
        is_error: bool = False,
    ) -> None:
        """Append one finished line to the run.

        Severity is never inferred from the stream a line was written
        to: this process prints through `term`, which writes even its
        informational messages to stderr.
        """
        if self._is_closed:
            return

        # There is no public API for writing a labeled line to a run.
        interface = self._run._interface
        if interface is None:
            return

        try:
            # nowait=True because this may run inside a print, which
            # must not block on the outgoing queue.
            interface.publish_run_log(
                line,
                label=label,
                is_error=is_error,
                nowait=True,
            )
        except Exception:
            # A failed write costs this line, never the sweep.
            pass
