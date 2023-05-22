import hashlib
import os
from typing import TYPE_CHECKING, Dict, Optional, Tuple

from wandb import env
from wandb.sdk.interface.artifacts import Artifact, ArtifactNotLoggedError
from wandb.sdk.lib.filesystem import mkdir_exists_ok
from wandb.sdk.lib.hashutil import B64MD5, ETag, b64_to_hex_id
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    from wandb.sdk import wandb_artifacts


class ArtifactsCache:
    _TMP_PREFIX = "tmp"

    def __init__(self, cache_dir: StrPath) -> None:
        self._cache_dir = cache_dir
        mkdir_exists_ok(self._cache_dir)
        self._md5_obj_dir = os.path.join(self._cache_dir, "obj", "md5")
        self._etag_obj_dir = os.path.join(self._cache_dir, "obj", "etag")
        self._artifacts_by_id: Dict[str, Artifact] = {}
        self._artifacts_by_client_id: Dict[str, "wandb_artifacts.Artifact"] = {}

    def check_md5_obj_path(
        self, b64_md5: B64MD5, size: int
    ) -> Tuple[FilePathStr, bool]:
        hex_md5 = b64_to_hex_id(b64_md5)
        path = os.path.join(self._cache_dir, "obj", "md5", hex_md5[:2], hex_md5[2:])
        hit = os.path.isfile(path) and os.path.getsize(path) == size
        return FilePathStr(path), hit

    # TODO(spencerpearson): this method at least needs its signature changed.
    # An ETag is not (necessarily) a checksum.
    def check_etag_obj_path(
        self,
        url: URIStr,
        etag: ETag,
        size: int,
    ) -> Tuple[FilePathStr, bool]:
        hexhash = hashlib.sha256(
            hashlib.sha256(url.encode("utf-8")).digest()
            + hashlib.sha256(etag.encode("utf-8")).digest()
        ).hexdigest()
        path = os.path.join(self._cache_dir, "obj", "etag", hexhash[:2], hexhash[2:])
        hit = os.path.isfile(path) and os.path.getsize(path) == size
        return FilePathStr(path), hit

    def get_artifact(self, artifact_id: str) -> Optional["Artifact"]:
        return self._artifacts_by_id.get(artifact_id)

    def store_artifact(self, artifact: "Artifact") -> None:
        if not artifact.id:
            raise ArtifactNotLoggedError(artifact, "store_artifact")
        self._artifacts_by_id[artifact.id] = artifact

    def get_client_artifact(
        self, client_id: str
    ) -> Optional["wandb_artifacts.Artifact"]:
        return self._artifacts_by_client_id.get(client_id)

    def store_client_artifact(self, artifact: "wandb_artifacts.Artifact") -> None:
        self._artifacts_by_client_id[artifact._client_id] = artifact

    def cleanup(self, target_size: int) -> int:
        bytes_reclaimed = 0
        paths = {}
        total_size = 0
        for root, _, files in os.walk(self._cache_dir):
            for file in files:
                try:
                    path = os.path.join(root, file)
                    stat = os.stat(path)

                    if file.startswith(ArtifactsCache._TMP_PREFIX):
                        os.remove(path)
                        bytes_reclaimed += stat.st_size
                        continue
                except OSError:
                    continue
                paths[path] = stat
                total_size += stat.st_size

        sorted_paths = sorted(paths.items(), key=lambda x: x[1].st_atime)
        for path, stat in sorted_paths:
            if total_size < target_size:
                return bytes_reclaimed

            try:
                os.remove(path)
            except OSError:
                pass

            total_size -= stat.st_size
            bytes_reclaimed += stat.st_size
        return bytes_reclaimed


_artifacts_cache = None


def get_artifacts_cache() -> ArtifactsCache:
    global _artifacts_cache
    if _artifacts_cache is None:
        cache_dir = os.path.join(env.get_cache_dir(), "artifacts")
        _artifacts_cache = ArtifactsCache(cache_dir)
    return _artifacts_cache
