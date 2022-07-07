import sys
import threading
from typing import Mapping, MutableMapping, TYPE_CHECKING
import tqdm
import time

import wandb


if TYPE_CHECKING:
    if sys.version_info >= (3, 8):
        from typing import TypedDict
    else:
        from typing_extensions import TypedDict

    class FileStats(TypedDict):
        deduped: bool
        total: int
        uploaded: int
        failed: bool
        artifact_file: bool

    class ArtifactStats(TypedDict):
        artifact_id: str
        name: str
        total_file_count: int
        pending_file_count: int
        lineno: int


class Stats:
    def __init__(self) -> None:
        self._stats: MutableMapping[str, "FileStats"] = {}
        self._artifact_stats: MutableMapping[str, "ArtifactStats"] = {}
        self._lock = threading.Lock()
        self._lineno = 0
        self.pbar = None

    def init_file(
        self, save_name: str, size: int, is_artifact_file: bool = False
    ) -> None:
        with self._lock:
            self._stats[save_name] = {
                "deduped": False,
                "total": size,
                "uploaded": 0,
                "failed": False,
                "artifact_file": is_artifact_file,
            }

    def set_file_deduped(self, save_name: str) -> None:
        file_stats = self._stats[save_name]
        file_stats["deduped"] = True
        file_stats["uploaded"] = file_stats["total"]

    def update_uploaded_file(self, save_name: str, total_uploaded: int) -> None:
        self._stats[save_name]["uploaded"] = total_uploaded

    def update_failed_file(self, save_name: str) -> None:
        self._stats[save_name]["uploaded"] = 0
        self._stats[save_name]["failed"] = True

    def init_artifact_stats(
        self, artifact_id: str, artifact_name: str, total_file_count: str
    ) -> None:
        with self._lock:
            if self._lineno == 0:
                with open("artifact_stats.txt", "w") as f:
                    f.write("Artifact Name\tPending files to be uploaded\n")

            self._lineno += 1
            self._artifact_stats[artifact_id] = {
                "artifact_id": artifact_id,
                "name": artifact_name,
                "total_file_count": total_file_count,
                "pending_file_count": total_file_count,
                "lineno": self._lineno,
            }
            # if self.pbar is None:
            #     self.pbar = tqdm.tqdm(total=total_file_count)

    def update_artifact_stats(self, artifact_id: str, pending_count: int):
        with self._lock:
            a = self._artifact_stats[artifact_id]
            name = a["name"]

            # this works but is inefficient for large files
            s = time.time()
            f = open("artifact_stats.txt", "r")
            lines = f.readlines()
            f.close()
            if a["lineno"] >= len(lines):
                lines.append(f"{name}\t{pending_count}\n")
            else:
                lines[a["lineno"]] = f"{name}\t{pending_count}\n"
            out = open("artifact_stats.txt", "w")
            out.writelines(lines)
            out.close()
            # print(f"Time elapsed for writing to file: {time.time() - s}")
            # print(f"{name}, {pending_count}")
            # self.pbar.update(a["total_file_count"] - pending_count)
            # if pending_count == 0:
            #     self.pbar.close()

    def summary(self) -> Mapping[str, int]:
        # Need to use list to ensure we get a copy, since other threads may
        # modify this while we iterate
        with self._lock:
            stats = list(self._stats.values())
        return {
            "uploaded_bytes": sum(f["uploaded"] for f in stats),
            "total_bytes": sum(f["total"] for f in stats),
            "deduped_bytes": sum(f["total"] for f in stats if f["deduped"]),
        }

    def file_counts_by_category(self) -> Mapping[str, int]:
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
            elif wandb.wandb_lib.filenames.is_wandb_file(save_name):  # type: ignore[attr-defined]  # TODO(spencerpearson): this is probably synonymous with wandb.sdk.lib.filenames...?
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
