"""Defines an object for printing run progress at the end of a script."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Iterator, NoReturn

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface import interface
from wandb.sdk.lib import asyncio_compat

from . import printer as p

_INDENT = "  "
_MAX_LINES_TO_PRINT = 6
_MAX_OPS_TO_PRINT = 5


async def loop_printing_operation_stats(
    progress: ProgressPrinter,
    interface: interface.InterfaceBase,
) -> None:
    """Poll and display ongoing tasks in the internal service process.

    This never returns and must be cancelled. This is meant to be used with
    `mailbox.wait_with_progress()`.

    Args:
        progress: The printer to update with operation stats.
        interface: The interface to use to poll for updates.

    Raises:
        HandleAbandonedError: If the mailbox associated with the interface
            becomes closed.
        Exception: Any other problem communicating with the service process.
    """
    stats: pb.OperationStats | None = None

    async def loop_update_screen() -> NoReturn:
        while True:
            if stats:
                progress.update(stats)
            await asyncio.sleep(0.1)

    async def loop_poll_stats() -> NoReturn:
        nonlocal stats
        while True:
            start_time = time.monotonic()

            handle = await interface.deliver_async(
                pb.Record(
                    request=pb.Request(operations=pb.OperationStatsRequest()),
                )
            )
            result = await handle.wait_async(timeout=None)
            stats = result.response.operations_response.operation_stats

            elapsed_time = time.monotonic() - start_time
            if elapsed_time < 0.5:
                await asyncio.sleep(0.5 - elapsed_time)

    async with asyncio_compat.open_task_group() as task_group:
        task_group.start_soon(loop_update_screen())
        task_group.start_soon(loop_poll_stats())


@contextlib.contextmanager
def progress_printer(
    printer: p.Printer,
    default_text: str,
) -> Iterator[ProgressPrinter]:
    """Context manager providing an object for printing run progress.

    Args:
        printer: The printer to use.
        default_text: The text to show if no information is available.
    """
    with printer.dynamic_text() as text_area:
        try:
            yield ProgressPrinter(
                printer,
                text_area,
                default_text=default_text,
            )
        finally:
            printer.progress_close()


class ProgressPrinter:
    """Displays PollExitResponse results to the user."""

    def __init__(
        self,
        printer: p.Printer,
        progress_text_area: p.DynamicText | None,
        default_text: str,
    ) -> None:
        self._printer = printer
        self._progress_text_area = progress_text_area
        self._default_text = default_text
        self._tick = -1
        self._last_printed_line = ""

    def update(
        self,
        stats_or_groups: pb.OperationStats | dict[str, pb.OperationStats],
    ) -> None:
        """Update the displayed information.

        Args:
            stats_or_groups: A single group of operations, or zero or more
                labeled operation groups.
        """
        self._tick += 1

        if not self._progress_text_area:
            line = self._to_static_text(stats_or_groups)
            if line and line != self._last_printed_line:
                self._printer.display(line)
                self._last_printed_line = line
            return

        lines = self._to_dynamic_text(stats_or_groups)
        if not lines:
            loading_symbol = self._printer.loading_symbol(self._tick)
            if loading_symbol:
                lines = [f"{loading_symbol} {self._default_text}"]
            else:
                lines = [self._default_text]

        self._progress_text_area.set_text("\n".join(lines))

    def _to_dynamic_text(
        self,
        stats_or_groups: pb.OperationStats | dict[str, pb.OperationStats],
    ) -> list[str]:
        """Returns text to show in a dynamic text area."""
        loading_symbol = self._printer.loading_symbol(self._tick)

        if isinstance(stats_or_groups, dict):
            return _GroupedOperationStatsPrinter(
                self._printer,
                _MAX_LINES_TO_PRINT,
                loading_symbol,
            ).render(stats_or_groups)

        else:
            return _OperationStatsPrinter(
                self._printer,
                _MAX_LINES_TO_PRINT,
                loading_symbol,
            ).render(stats_or_groups)

    def _to_static_text(
        self,
        stats_or_groups: pb.OperationStats | dict[str, pb.OperationStats],
    ) -> str:
        """Returns a single line of text to print out."""
        if isinstance(stats_or_groups, dict):
            sorted_prefixed_stats = list(
                (f"[{group}] ", stats)  #
                for group, stats in sorted(stats_or_groups.items())
            )
        else:
            sorted_prefixed_stats = [("", stats_or_groups)]

        group_strs: list[str] = []
        total_operations = 0
        total_printed = 0

        for prefix, stats in sorted_prefixed_stats:
            total_operations += stats.total_operations
            if not stats.operations:
                continue

            group_ops: list[str] = []
            i = 0
            while total_printed < _MAX_OPS_TO_PRINT and i < len(stats.operations):
                group_ops.append(stats.operations[i].desc)
                total_printed += 1
                i += 1

            if group_ops:
                group_strs.append(prefix + "; ".join(group_ops))

        line = "; ".join(group_strs)
        remaining = total_operations - total_printed
        if total_printed > 0 and remaining > 0:
            line += f" (+ {remaining} more)"

        return line


class _GroupedOperationStatsPrinter:
    """Renders a list of labeled operation stats groups into lines of text."""

    def __init__(
        self,
        printer: p.Printer,
        max_lines: int,
        loading_symbol: str,
    ) -> None:
        self._printer = printer
        self._max_lines = max_lines
        self._loading_symbol = loading_symbol

    def render(self, groups: dict[str, pb.OperationStats]) -> list[str]:
        """Convert labeled operation stats groups into text to display.

        Args:
            groups: A mapping from group labels to stats for that group.

        Returns:
            The lines of text to print. The lines do not end with the newline
            character. Returns an empty list if there are no operations.
        """
        lines: list[str] = []

        for key, stats in sorted(groups.items()):
            # Don't display empty groups.
            if not stats.operations:
                continue

            # Ensure enough space left for the group header and at least
            # one line of content.
            remaining_lines = self._max_lines - len(lines)
            if remaining_lines < 2:
                break

            # Group header.
            lines.append(key)

            # Group content.
            stats_lines = _OperationStatsPrinter(
                printer=self._printer,
                max_lines=remaining_lines - 1,  # minus one for the header
                loading_symbol=self._loading_symbol,
            ).render(stats)
            for line in stats_lines:
                lines.append(f"{_INDENT}{line}")

        return lines


class _OperationStatsPrinter:
    """Renders operation stats into lines of text."""

    def __init__(
        self,
        printer: p.Printer,
        max_lines: int,
        loading_symbol: str,
    ) -> None:
        self._printer = printer
        self._max_lines = max_lines
        self._loading_symbol = loading_symbol

        self._lines: list[str] = []
        self._ops_shown = 0

    def render(self, stats: pb.OperationStats) -> list[str]:
        """Convert the stats into a list of lines to display.

        Args:
            stats: Collection of operations to display.

        Returns:
            The lines of text to print. The lines do not end with the newline
            character. Returns an empty list if there are no operations.
        """
        for op in stats.operations:
            self._add_operation(op, is_subtask=False, indent="")

        if self._ops_shown < stats.total_operations:
            if 1 <= self._max_lines <= len(self._lines):
                self._ops_shown -= 1
                self._lines.pop()

            remaining = stats.total_operations - self._ops_shown

            self._lines.append(f"+ {remaining} more task(s)")

        return self._lines

    def _add_operation(self, op: pb.Operation, is_subtask: bool, indent: str) -> None:
        """Add the operation to `self._lines`."""
        if len(self._lines) >= self._max_lines:
            return

        if not is_subtask:
            self._ops_shown += 1

        parts: list[str] = []

        # Subtask indicator.
        if is_subtask and self._printer.supports_unicode:
            parts.append("↳")

        # Loading symbol.
        if self._loading_symbol:
            parts.append(self._loading_symbol)

        # Task name.
        parts.append(op.desc)

        # Progress information.
        if op.progress:
            parts.append(f"{op.progress}")

        # Task duration.
        parts.append(f"({_time_to_string(seconds=op.runtime_seconds)})")

        # Error status.
        self._lines.append(indent + " ".join(parts))
        if op.error_status:
            error_word = self._printer.error("ERROR")
            error_desc = self._printer.secondary_text(op.error_status)
            subtask_indent = "  " if is_subtask else ""
            self._lines.append(
                f"{indent}{subtask_indent}  {error_word} {error_desc}",
            )

        # Subtasks.
        if op.subtasks:
            subtask_indent = indent + _INDENT
            for task in op.subtasks:
                self._add_operation(
                    task,
                    is_subtask=True,
                    indent=subtask_indent,
                )


def _time_to_string(seconds: float) -> str:
    """Returns a short string representing the duration."""
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 60 * 60:
        minutes = seconds / 60
        return f"{minutes:.1f}m"

    hours = int(seconds / (60 * 60))
    minutes = int((seconds / 60) % 60)
    return f"{hours}h{minutes}m"
