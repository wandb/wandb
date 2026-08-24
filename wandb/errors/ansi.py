"""Handling for ANSI sequences."""

from __future__ import annotations

import re
from collections.abc import Generator

_MULTI_ANSI_RE = re.compile("(\x1b\\[(K|.*?m))+")
"""Regexp that greedily matches one or more SGR ANSI sequences."""


def wrap_ansi(text: str, *, width: int, max_lines: int) -> Generator[str]:
    """Wrap the ANSI-containing text to fit into the given width.

    For this purpose, "ANSI sequences" refers to "SGR" ANSI sequences,
    basically text styling. This matches the logic `click` uses to strip
    ANSI sequences.

    All ANSI sequences in the text are preserved and appear at the end of the
    last line even on truncation, in case they contain style reset commands.

    All characters outside of ANSI sequences in the text are assumed to take
    up 1 column in the terminal. Wide characters, like emoji or east-Asian
    text, will break the output. Likewise, text must not contain any control
    characters like newlines or carriage returns.

    Args:
        text: Text without newlines but possibly containing ANSI sequences.
        width: The maximum printed length of each returned line.
        max_lines: The maximum number of lines to emit. If the text does not
            fit on this many lines, an ellipsis is emitted at the end.

    Yields:
        Wrapped lines. The lines do not end with newline characters.
        Unless max_lines is zero, at least one line is yielded.
    """
    if max_lines <= 0:
        return

    # If the text is empty, output an empty line.
    #
    # Given zero width, output a single zero-width line with any ANSI sequences
    # from the text to avoid spam. We don't really care about this edge case
    # anyway. Could happen if `width` is the result of a calculation.
    if not text or width < 1:
        yield "".join(
            text[ansi_start:ansi_end]
            for ansi_start, ansi_end in _AnsiCursor(text).remaining_ansi_runs()
        )
        return

    cursor = _AnsiCursor(text)

    # For all lines but the last, just grab up to `width` characters.
    for _ in range(max_lines - 1):
        line_start = cursor.index
        cursor.forward(width)
        yield text[line_start : cursor.index]

        if cursor.index >= len(text):
            return

    # Shorten the remaining text with an ellipsis on the last line, if needed.
    yield _shorten_remaining(cursor, text, width=width)


def _shorten_remaining(cursor: _AnsiCursor, text: str, *, width: int) -> str:
    """Returns the rest of the text from the cursor position, truncated."""
    line_start = cursor.index
    ellipsis_len = min(3, width)

    # First save the truncation position for an ellipsis.
    cursor.forward(width - ellipsis_len)
    ellipsis_index = cursor.index
    ansi_after_ellipsis = cursor.remaining_ansi_runs()
    cursor.forward(ellipsis_len)

    # If the remaining text fits on this final line, return it.
    if cursor.index == len(text):
        return text[line_start:]

    # Otherwise, truncate and add an ellipsis.
    line_parts: list[str] = []
    line_parts.append(text[line_start:ellipsis_index])
    line_parts.append("." * ellipsis_len)
    line_parts.extend(text[start:end] for start, end in ansi_after_ellipsis)

    return "".join(line_parts)


class _AnsiCursor:
    """An ANSI-aware index into a string."""

    def __init__(self, text: str) -> None:
        self._text_len = len(text)
        self._ansi_runs: list[tuple[int, int]] = [
            (match.start(0), match.end(0))  #
            for match in _MULTI_ANSI_RE.finditer(text)
        ]
        """Start and end indices of all ANSI runs in the text, in order."""

        self._ansi_before_cursor = 0
        """Count of ANSI runs before the current cursor position.

        This is also the index of the ANSI run after the cursor, if any.
        """

        self._index = 0
        """The cursor's index into the text.

        Never in the middle of an ANSI sequence.
        """

    @property
    def index(self) -> int:
        """The index in the string corresponding to the cursor position."""
        return self._index

    def remaining_ansi_runs(self) -> list[tuple[int, int]]:
        """Returns (start, end) indices of all ANSI runs after the cursor."""
        return self._ansi_runs[self._ansi_before_cursor :]

    def forward(self, count: int) -> None:
        """Move the cursor forward by `count` printable characters.

        If the cursor lands on a run of ANSI codes, the index will be set to
        after the run. In particular, if there are `count` or fewer printable
        characters remaining, the index becomes the length of the string.
        """
        while count > 0 and self._index < self._text_len:
            # No ANSI runs after the cursor, so just jump forward.
            if self._ansi_before_cursor >= len(self._ansi_runs):
                self._index = min(self._index + count, self._text_len)
                return

            next_ansi = self._ansi_runs[self._ansi_before_cursor]
            count_to_next_ansi = next_ansi[0] - self._index

            # Enough characters before the next ANSI run, so just jump forward.
            if count < count_to_next_ansi:
                self._index += count
                return

            # Jump to the end of the next ANSI run, then continue.
            count -= count_to_next_ansi
            self._index = next_ansi[1]
            self._ansi_before_cursor += 1
