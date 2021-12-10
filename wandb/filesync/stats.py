import threading

import wandb


class Stats:
    def __init__(self):
        self._stats = {}
        self._lock = threading.Lock()

    def init_file(self, save_name, size, is_artifact_file=False):
        with self._lock:
            self._stats[save_name] = {
                "deduped": False,
                "total": size,
                "uploaded": 0,
                "failed": False,
                "artifact_file": is_artifact_file,
            }

    def set_file_deduped(self, save_name):
        file_stats = self._stats[save_name]
        file_stats["deduped"] = True
        file_stats["uploaded"] = file_stats["total"]

    def update_uploaded_file(self, save_name, total_uploaded):
        self._stats[save_name]["uploaded"] = total_uploaded

    def update_failed_file(self, save_name):
        self._stats[save_name]["uploaded"] = 0
        self._stats[save_name]["failed"] = True

    def summary(self):
        # Need to use list to ensure we get a copy, since other threads may
        # modify this while we iterate
        with self._lock:
            stats = list(self._stats.values())
        return {
            "uploaded_bytes": sum(f["uploaded"] for f in stats),
            "total_bytes": sum(f["total"] for f in stats),
            "deduped_bytes": sum(f["total"] for f in stats if f["deduped"]),
        }

    def file_counts_by_category(self):
        artifact_files = 0
        wandb_files = 0
        media_files = 0
        other_files = 0
        # Need to use list to ensure we get a copy, since other threads may
        # modify this while we iterate
        with self._lock:
            file_stats = list(self._stats.items())
        for save_name, stats in file_stats:
            if stats["artifact_file"]:
                artifact_files += 1
            elif wandb.wandb_lib.filenames.is_wandb_file(save_name):
                wandb_files += 1
            elif save_name.startswith("media"):
                media_files += 1
            else:
                other_files += 1
        return {
            "artifact": artifact_files,
            "wandb": wandb_files,
            "media": media_files,
            "other": other_files,
        }
