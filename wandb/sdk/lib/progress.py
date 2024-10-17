"""Defines an object for printing run progress at the end of a script."""

from __future__ import annotations

import contextlib
from typing import Iterator

from wandb.proto import wandb_internal_pb2

from . import printer as p


def print_sync_dedupe_stats(
    printer: p.Printer,
    final_result: wandb_internal_pb2.PollExitResponse,
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
) -> Iterator[ProgressPrinter]:
    """Context manager providing an object for printing run progress."""
    with printer.dynamic_text() as text_area:
        yield ProgressPrinter(printer, text_area)
        printer.progress_close()


class ProgressPrinter:
    """Displays PollExitResponse results to the user."""

    def __init__(
        self,
        printer: p.Printer,
        progress_text_area: p.DynamicText | None,
    ) -> None:
        self._printer = printer
        self._progress_text_area = progress_text_area

    def update(
        self,
        progress: list[wandb_internal_pb2.PollExitResponse],
    ) -> None:
        """Update the displayed information."""
        if not progress:
            return

        if len(progress) == 1:
            self._update_single_run(progress[0])
        else:
            self._update_multiple_runs(progress)

    def _update_single_run(
        self,
        progress: wandb_internal_pb2.PollExitResponse,
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
        progress_list: list[wandb_internal_pb2.PollExitResponse],
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


def _megabytes(bytes: int) -> float:
    """Return the number of megabytes in `bytes`."""
    return bytes / (1 << 20)
