from __future__ import annotations

import os
import pathlib
import subprocess
import time
from collections.abc import Sequence

import click
import pytest

# Will skip on Windows.
pytest.importorskip("pty")
import pty  # Import using normal syntax for IDE support.

_TESTER_SCRIPT = pathlib.Path(__file__).parent / "terminput_tester.py"


class _TtyTester:
    """Helps test a subprocess's tty usage.

    This requires some low level control:

    * We use openpty() to get file descriptors for a "pseudoterminal" which
      implements nice functionality like "turn the Ctrl+C character into a
      SIGINT"
    * The child script has to make the pseudoterminal its controlling
      terminal (so that it knows where to send the SIGINT in the above
      example)

    The low level os.read() and os.write() are necessary to implement timeouts.
    """

    def __init__(
        self,
        script: pathlib.Path,
        args: Sequence[str] | None = None,
        timeout: float = 10,
    ) -> None:
        """Start the script as a Python subprocess connected to a pty.

        Args:
            script: Path to the script to start.
            timeout: Timeout in seconds for most operations.
        """
        self._script = script
        self._timeout = timeout
        self._timer = 0
        self._buffer = bytearray()

        # Create a pseudoterminal.
        #
        # This returns two file descriptors: a "parent" and a "child".
        # They're connected to the pseudoterminal like this:
        #
        #   parent  <->  pty  <->  child
        #
        # The parent side is us. We can read from it to get the "displayed"
        # bytes. Any bytes we write to it are sent to the child
        # and possibly echoed back to us (like in a real terminal).
        #
        # The child side is for the subprocess. The subprocess can read it
        # to receive bytes written on the parent side and can write to it
        # to output bytes to the parent side.
        self._parent_fd, child_fd = pty.openpty()
        self._proc = subprocess.Popen(
            ("python", self._script, *(args or [])),
            stdin=child_fd,
            stderr=child_fd,
            stdout=child_fd,
        )

        # Close our copy of the child FD as we no longer need it.
        os.close(child_fd)

        # We must use low-level operations to read the parent FD.
        # We need non-blocking reads to implement timeouts.
        os.set_blocking(self._parent_fd, False)

    def __enter__(self) -> _TtyTester:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._reset_timer()

        try:
            self._read_and_wait_for_proc()
        except TimeoutError:
            self._proc.kill()
        finally:
            os.close(self._parent_fd)

    def unstyled_output(self) -> list[str]:
        """Returns all text read so far without ANSI sequences."""
        return click.unstyle(self.all_output().decode()).splitlines()

    def all_output(self) -> bytes:
        """Returns all bytes output by the subprocess so far.

        Can be used after exiting the context manager.
        """
        return bytes(self._buffer)

    def wait_for_text(self, text: bytes) -> None:
        """Block until the given text has been output by the subprocess."""
        self._reset_timer()
        while text not in self._buffer:
            self._read_more()
            self._check_timeout()

    def send_input(self, text: bytes) -> None:
        """Write text to the process's stdin."""
        self._reset_timer()
        total_written = 0
        while total_written < len(text):
            total_written += os.write(self._parent_fd, text[total_written:])
            self._check_timeout()

    def _read_and_wait_for_proc(self) -> None:
        """Read the process's output until it terminates, or time out."""

        while True:
            data = self._read_chunk()

            if data:
                self._buffer.extend(data)
            elif self._proc.poll() is not None:
                break

            time.sleep(0.01)
            self._check_timeout()

    def _read_more(self) -> None:
        """Block until at least one more byte is read, or time out."""
        while not (data := self._read_chunk()):
            time.sleep(0.01)
            self._check_timeout()
        self._buffer.extend(data)

    def _read_chunk(self) -> bytes | None:
        """Read a chunk of data if any is available."""
        try:
            return os.read(self._parent_fd, 1024)
        except OSError:
            # On macOS, only a BlockingIOError is possible.
            # On Linux, this can also be an OSError after the child process
            # shuts down.
            return None

    def _reset_timer(self) -> None:
        """Reset the timeout timer."""
        self._timer = time.monotonic()

    def _check_timeout(self) -> None:
        """Raise if too much time has passed since _reset_timer()."""
        time_passed = time.monotonic() - self._timer
        if time_passed > self._timeout:
            message = (
                f"Timed out after {time_passed:.2g}s."
                f" Text so far: {self._buffer.decode()}"
            )
            raise TimeoutError(message)


def test_basic_prompt():
    with _TtyTester(_TESTER_SCRIPT) as tester:
        tester.wait_for_text(b"PROMPT: ")
        tester.send_input(b"the prompt\n")

    assert tester.unstyled_output() == [
        "wandb: PROMPT: the prompt",
        "Got result: the prompt",
        "DONE",
    ]


def test_abort():
    with _TtyTester(_TESTER_SCRIPT) as tester:
        tester.wait_for_text(b"PROMPT: ")

        tester.send_input(b"this may be ignored")
        # 3 is the ASCII code for Ctrl+C, understood by the pty.
        tester.send_input(b"\x03")

    lines = tester.unstyled_output()
    assert lines[0] in (
        # On macOS:
        "wandb: PROMPT: ^C",
        # On Linux:
        "wandb: PROMPT: this may be ignored^C",
    )
    assert lines[1:] == [
        "INTERRUPT!",
    ]


def test_abort_timeout():
    with _TtyTester(_TESTER_SCRIPT, args=["--timeout", "10"]) as tester:
        tester.wait_for_text(b"PROMPT: ")

        tester.send_input(b"this may be ignored")
        # 3 is the ASCII code for Ctrl+C, understood by the pty.
        tester.send_input(b"\x03")

    lines = tester.unstyled_output()
    assert lines[0] in (
        # On macOS:
        "wandb: PROMPT: (10 second timeout) ^C",
        # On Linux:
        "wandb: PROMPT: (10 second timeout) this may be ignored^C",
    )
    assert lines[1:] == [
        "INTERRUPT!",
    ]


def test_hidden_prompt():
    with _TtyTester(_TESTER_SCRIPT, args=["--hide"]) as tester:
        tester.wait_for_text(b"PROMPT: ")
        tester.send_input(b"the prompt\n")

    assert tester.unstyled_output() == [
        "wandb: PROMPT: ",
        "Got result: the prompt",
        "DONE",
    ]


def test_timeout():
    with _TtyTester(_TESTER_SCRIPT, args=["--timeout", "0.1"]) as tester:
        # Don't send any input, just let it time out.
        pass

    assert tester.unstyled_output() == [
        "wandb: PROMPT: (0 second timeout) ",
        "TIMEOUT!",
    ]
