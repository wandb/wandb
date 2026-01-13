from __future__ import annotations

from itertools import takewhile

import pyte
import pyte.modes
import pytest
from wandb.errors import term


@pytest.fixture
def emulated_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> EmulatedTerminal:
    """Emulates a terminal for the duration of a test.

    This makes functions in the `wandb.errors.term` module act as if
    we're connected to a terminal.

    NOTE: This resets pytest's stderr and stdout buffers. You should not
    use this with anything else that uses capsys.
    """
    terminal = EmulatedTerminal(capsys)

    # Allow dynamic_text().
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(term, "_sys_stderr_isatty", lambda: True)

    # Allow terminput().
    monkeypatch.setattr(term, "can_use_terminput", lambda: True)
    monkeypatch.setattr(term, "_terminput", terminal.terminput)

    # Make click pretend we're a TTY, so it doesn't strip ANSI sequences.
    # This is fragile and could break when click is updated.
    monkeypatch.setattr("click._compat.isatty", lambda *args, **kwargs: True)

    return terminal


class EmulatedTerminal:
    """The return value of the emulated_terminal fixture."""

    def __init__(self, capsys: pytest.CaptureFixture[str]):
        self._capsys = capsys
        self._screen = pyte.Screen(80, 24)
        self._screen.set_mode(pyte.modes.LNM)  # \n implies \r
        self._stream = pyte.Stream(self._screen)
        self._inputs: list[str] = []

    def reset_capsys(self) -> None:
        """Reset pytest's captured stderr and stdout buffers."""
        self._capsys.readouterr()

    def read_stderr(self) -> list[str]:
        """Returns the text in the emulated terminal.

        This processes the stderr text captured by pytest since the last
        invocation and returns the updated state of the screen. Empty lines
        at the top and bottom of the screen and empty text at the end of
        any line are trimmed.

        NOTE: This resets pytest's stderr and stdout buffers. You should not
        use this with anything else that uses capsys.
        """
        self._process_captured_text()

        lines = [line.rstrip() for line in self._screen.display]

        # Trim empty lines from the start and end of the screen.
        n_empty_at_start = sum(1 for _ in takewhile(lambda line: not line, lines))
        n_empty_at_end = sum(1 for _ in takewhile(lambda line: not line, lines[::-1]))
        return lines[n_empty_at_start:-n_empty_at_end]

    def queue_input(self, text: str) -> None:
        """Queue the next terminput return value."""
        self._inputs.append(text)

    def terminput(
        self,
        prefixed_prompt: str,
        *,
        timeout: float | None = None,
        hide: bool = False,
    ) -> str:
        """A fake implementation of term._terminput().

        Raises an assertion error if no inputs are queued.
        """
        # Simulate printing the prompt.
        self._process_captured_text()
        self._stream.feed(prefixed_prompt)

        if not self._inputs:
            if timeout is not None:
                raise TimeoutError
            else:
                raise AssertionError("terminput() used, but no inputs queued.")

        input = self._inputs.pop(0)

        # Simulate printing the input and the return key press.
        if not hide:
            self._stream.feed(f"{input}\n")
        else:
            self._stream.feed("\n")

        return input

    def _process_captured_text(self) -> None:
        """Read capsys and update the terminal state."""
        self._stream.feed(self._capsys.readouterr().err)
