"""Defines an object for printing run progress at the end of a script."""

from __future__ import annotations

import contextlib
from typing import Iterable, Iterator

import wandb
from wandb.proto import wandb_internal_pb2 as pb

from . import printer as p


def print_sync_dedupe_stats(
    printer: p.Printer,
    final_result: pb.PollExitResponse,
) -> None:
    """Print how much W&B sync reduced the amount of uploaded data.

    Args:
        final_result: The final PollExit result.
    """
    deduped_bytes = final_result.pusher_stats.deduped_bytes
    total_bytes = final_result.pusher_stats.total_bytes

    if total_bytes <= 0 or deduped_bytes <= 0:
        return

    frac = deduped_bytes / total_bytes
    printer.display(f"W&B sync reduced upload amount by {frac:.1%}")


@contextlib.contextmanager
def progress_printer(
    printer: p.Printer,
    settings: wandb.Settings | None = None,
) -> Iterator[ProgressPrinter]:
    """Context manager providing an object for printing run progress."""
    with printer.dynamic_text() as text_area:
        yield ProgressPrinter(printer, text_area, settings)
        printer.progress_close()


class ProgressPrinter:
    """Displays PollExitResponse results to the user."""

    def __init__(
        self,
        printer: p.Printer,
        progress_text_area: p.DynamicText | None,
        settings: wandb.Settings | None,
    ) -> None:
        self._show_operation_stats = settings and settings._show_operation_stats
        self._printer = printer
        self._progress_text_area = progress_text_area
        self._tick = 0
        self._last_printed_line = ""

    def update(
        self,
        progress: list[pb.PollExitResponse],
    ) -> None:
        """Update the displayed information."""
        if not progress:
            return

        if self._show_operation_stats:
            self._update_operation_stats(
                list(response.operation_stats for response in progress)
            )
        elif len(progress) == 1:
            self._update_single_run(progress[0])
        else:
            self._update_multiple_runs(progress)

        self._tick += 1

    def _update_operation_stats(self, stats_list: list[pb.OperationStats]) -> None:
        if self._progress_text_area:
            _DynamicOperationStatsPrinter(
                self._printer,
                self._progress_text_area,
                max_lines=6,
                loading_symbol=self._printer.loading_symbol(self._tick),
            ).display(stats_list)

        else:
            top_level_operations: list[str] = []
            extra_operations = 0
            for stats in stats_list:
                for op in stats.operations:
                    if len(top_level_operations) < 5:
                        top_level_operations.append(op.desc)
                    else:
                        extra_operations += 1

            line = "; ".join(top_level_operations)
            if extra_operations > 0:
                line += f" (+ {extra_operations} more)"

            if line != self._last_printed_line:
                self._printer.display(line)

            self._last_printed_line = line

    def _update_single_run(
        self,
        progress: pb.PollExitResponse,
    ) -> None:
        stats = progress.pusher_stats
        line = (
            f"{_megabytes(stats.uploaded_bytes):.3f} MB"
            f" of {_megabytes(stats.total_bytes):.3f} MB uploaded"
        )

        if stats.deduped_bytes > 0:
            line += f" ({_megabytes(stats.deduped_bytes):.3f} MB deduped)"

        if stats.total_bytes > 0:
            self._update_progress_text(
                line,
                stats.uploaded_bytes / stats.total_bytes,
            )
        else:
            self._update_progress_text(line, 1.0)

    def _update_multiple_runs(
        self,
        progress_list: list[pb.PollExitResponse],
    ) -> None:
        total_files = 0
        uploaded_bytes = 0
        total_bytes = 0

        for progress in progress_list:
            total_files += progress.file_counts.wandb_count
            total_files += progress.file_counts.media_count
            total_files += progress.file_counts.artifact_count
            total_files += progress.file_counts.other_count

            uploaded_bytes += progress.pusher_stats.uploaded_bytes
            total_bytes += progress.pusher_stats.total_bytes

        line = (
            f"Processing {len(progress_list)} runs with {total_files} files"
            f" ({_megabytes(uploaded_bytes):.2f} MB"
            f" / {_megabytes(total_bytes):.2f} MB)"
        )

        if total_bytes > 0:
            self._update_progress_text(line, uploaded_bytes / total_bytes)
        else:
            self._update_progress_text(line, 1.0)

    def _update_progress_text(self, text: str, progress: float) -> None:
        if self._progress_text_area:
            self._progress_text_area.set_text(text)
        else:
            self._printer.progress_update(text + "\r", progress)


class _DynamicOperationStatsPrinter:
    """Single-use object that writes operation stats into a text area."""

    def __init__(
        self,
        printer: p.Printer,
        text_area: p.DynamicText,
        max_lines: int,
        loading_symbol: str,
    ) -> None:
        self._printer = printer
        self._text_area = text_area
        self._max_lines = max_lines
        self._loading_symbol = loading_symbol

        self._lines: list[str] = []
        self._ops_shown = 0

    def display(
        self,
        stats_list: Iterable[pb.OperationStats],
    ) -> None:
        """Show the given stats in the text area."""
        total_operations = 0
        for stats in stats_list:
            for op in stats.operations:
                self._add_operation(op, is_subtask=False, indent="")
            total_operations += stats.total_operations

        if self._ops_shown < total_operations:
            # NOTE: In Python 3.8, we'd use a chained comparison here.
            if 1 <= self._max_lines and self._max_lines <= len(self._lines):
                self._lines.pop()

            remaining = total_operations - self._ops_shown

            self._lines.append(f"+ {remaining} more task(s)")

        if len(self._lines) == 0:
            if self._loading_symbol:
                self._text_area.set_text(f"{self._loading_symbol} Finishing up...")
            else:
                self._text_area.set_text("Finishing up...")
        else:
            self._text_area.set_text("\n".join(self._lines))

    def _add_operation(self, op: pb.Operation, is_subtask: bool, indent: str) -> None:
        """Add the operation to `self._lines`."""
        if len(self._lines) >= self._max_lines:
            return

        if not is_subtask:
            self._ops_shown += 1

        parts = []

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
            subtask_indent = indent + "  "
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


def _megabytes(bytes: int) -> float:
    """Returns the number of megabytes in `bytes`."""
    return bytes / (1 << 20)
