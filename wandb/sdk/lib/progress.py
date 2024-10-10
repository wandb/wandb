"""Defines an object for printing run progress at the end of a script."""

from __future__ import annotations

from wandb.proto import wandb_internal_pb2

from . import printer as p


def print_sync_dedupe_stats(
    printer: p.PrinterJupyter | p.PrinterTerm,
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


class ProgressPrinter:
    """Displays PollExitResponse results to the user."""

    def __init__(
        self,
        printer: p.PrinterJupyter | p.PrinterTerm,
    ) -> None:
        self._printer = printer

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

    def finish(self) -> None:
        """Mark as done.

        After this, `update` must not be used.
        """
        self._printer.progress_close()

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

        line += "\r"

        if stats.total_bytes > 0:
            self._printer.progress_update(
                line,
                stats.uploaded_bytes / stats.total_bytes,
            )
        else:
            self._printer.progress_update(line, 1.0)

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
            f" / {_megabytes(total_bytes):.2f} MB)\r"
        )

        if total_bytes > 0:
            self._printer.progress_update(line, uploaded_bytes / total_bytes)
        else:
            self._printer.progress_update(line, 1.0)


def _megabytes(bytes: int) -> float:
    """Return the number of megabytes in `bytes`."""
    return bytes / (1 << 20)
