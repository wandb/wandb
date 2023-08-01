import threading
from typing import MutableMapping, NamedTuple

import wandb


class FileStats(NamedTuple):
    deduped: bool
    total: int
    uploaded: int
    failed: bool
    artifact_file: bool


class Summary(NamedTuple):
    uploaded_bytes: int
    total_bytes: int
    deduped_bytes: int


class FileCountsByCategory(NamedTuple):
    artifact: int
    wandb: int
    media: int
    other: int


class Stats:
    def __init__(self) -> None:
        self._stats: MutableMapping[str, FileStats] = {}
        self._lock = threading.Lock()

    def init_file(
        self, save_name: str, size: int, is_artifact_file: bool = False
    ) -> None:
        with self._lock:
            self._stats[save_name] = FileStats(
                deduped=False,
                total=size,
                uploaded=0,
                failed=False,
                artifact_file=is_artifact_file,
            )

    def set_file_deduped(self, save_name: str) -> None:
        with self._lock:
            orig = self._stats[save_name]
            self._stats[save_name] = orig._replace(
                deduped=True,
                uploaded=orig.total,
            )

    def update_uploaded_file(self, save_name: str, total_uploaded: int) -> None:
        with self._lock:
            self._stats[save_name] = self._stats[save_name]._replace(
                uploaded=total_uploaded,
            )

    def update_failed_file(self, save_name: str) -> None:
        with self._lock:
            self._stats[save_name] = self._stats[save_name]._replace(
                uploaded=0,
                failed=True,
            )

    def summary(self) -> Summary:
        # Need to use list to ensure we get a copy, since other threads may
        # modify this while we iterate
        with self._lock:
            stats = list(self._stats.values())
        return Summary(
            uploaded_bytes=sum(f.uploaded for f in stats),
            total_bytes=sum(f.total for f in stats),
            deduped_bytes=sum(f.total for f in stats if f.deduped),
        )

    def file_counts_by_category(self) -> FileCountsByCategory:
        artifact_files = 0
        wandb_files = 0
        media_files = 0
        other_files = 0
        # Need to use list to ensure we get a copy, since other threads may
        # modify this while we iterate
        with self._lock:
            file_stats = list(self._stats.items())
        for save_name, stats in file_stats:
            if stats.artifact_file:
                artifact_files += 1
            elif wandb.wandb_lib.filenames.is_wandb_file(save_name):  # type: ignore[attr-defined]  # TODO(spencerpearson): this is probably synonymous with wandb.sdk.lib.filenames...?
                wandb_files += 1
            elif save_name.startswith("media"):
                media_files += 1
            else:
                other_files += 1
        return FileCountsByCategory(
            artifact=artifact_files,
            wandb=wandb_files,
            media=media_files,
            other=other_files,
        )
