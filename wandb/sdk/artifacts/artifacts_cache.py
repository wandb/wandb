"""Artifact cache."""
import contextlib
import errno
import hashlib
import os
import secrets
import shutil
from typing import IO, TYPE_CHECKING, ContextManager, Dict, Generator, Optional, Tuple

import wandb
from wandb import env, util
from wandb.errors import term
from wandb.sdk.artifacts.exceptions import ArtifactNotLoggedError
from wandb.sdk.lib.capped_dict import CappedDict
from wandb.sdk.lib.filesystem import mkdir_exists_ok
from wandb.sdk.lib.hashutil import B64MD5, ETag, b64_to_hex_id
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    import sys

    from wandb.sdk.artifacts.artifact import Artifact

    if sys.version_info >= (3, 8):
        from typing import Protocol
    else:
        from typing_extensions import Protocol

    class Opener(Protocol):
        def __call__(self, mode: str = ...) -> ContextManager[IO]:
            pass


class ArtifactsCache:
    _TMP_PREFIX = "tmp"

    def __init__(self, cache_dir: StrPath) -> None:
        self._cache_dir = cache_dir
        self._md5_obj_dir = os.path.join(self._cache_dir, "obj", "md5")
        self._etag_obj_dir = os.path.join(self._cache_dir, "obj", "etag")
        self._artifacts_by_id: Dict[str, Artifact] = CappedDict()
        self._artifacts_by_client_id: Dict[str, Artifact] = CappedDict()

    def check_md5_obj_path(
        self, b64_md5: B64MD5, size: int
    ) -> Tuple[FilePathStr, bool, "Opener"]:
        hex_md5 = b64_to_hex_id(b64_md5)
        path = os.path.join(self._cache_dir, "obj", "md5", hex_md5[:2], hex_md5[2:])
        return self._check_or_create(path, size)

    # TODO(spencerpearson): this method at least needs its signature changed.
    # An ETag is not (necessarily) a checksum.
    def check_etag_obj_path(
        self,
        url: URIStr,
        etag: ETag,
        size: int,
    ) -> Tuple[FilePathStr, bool, "Opener"]:
        hexhash = hashlib.sha256(
            hashlib.sha256(url.encode("utf-8")).digest()
            + hashlib.sha256(etag.encode("utf-8")).digest()
        ).hexdigest()
        path = os.path.join(self._cache_dir, "obj", "etag", hexhash[:2], hexhash[2:])
        return self._check_or_create(path, size)

    def _check_or_create(
        self, path: StrPath, size: int
    ) -> Tuple[FilePathStr, bool, "Opener"]:
        opener = self._cache_opener(path, size)
        hit = os.path.isfile(path) and os.path.getsize(path) == size
        return FilePathStr(str(path)), hit, opener

    def get_artifact(self, artifact_id: str) -> Optional["Artifact"]:
        return self._artifacts_by_id.get(artifact_id)

    def store_artifact(self, artifact: "Artifact") -> None:
        if not artifact.id:
            raise ArtifactNotLoggedError(artifact, "store_artifact")
        self._artifacts_by_id[artifact.id] = artifact

    def get_client_artifact(self, client_id: str) -> Optional["Artifact"]:
        return self._artifacts_by_client_id.get(client_id)

    def store_client_artifact(self, artifact: "Artifact") -> None:
        self._artifacts_by_client_id[artifact._client_id] = artifact

    def cleanup(
        self,
        target_size: Optional[int] = None,
        target_fraction: Optional[float] = None,
        remove_temp: bool = False,
    ) -> int:
        """Clean up the cache, removing the least recently used files first.

        Args:
            target_size: The target size of the cache in bytes. If the cache is larger
                than this, we will remove the least recently used files until the cache
                is smaller than this size.
            target_fraction: The target fraction of the cache to reclaim. If the cache
                is larger than this, we will remove the least recently used files until
                the cache is smaller than this fraction of its current size. It is an
                error to specify both target_size and target_fraction.
            remove_temp: Whether to remove temporary files. Temporary files are files
                that are currently being written to the cache. If remove_temp is True,
                all temp files will be removed, regardless of the target_size or
                target_fraction.

        Returns:
            The number of bytes reclaimed.
        """
        if target_size is None and target_fraction is None:
            # Default to clearing the entire cache.
            target_size = 0
        if target_size is not None and target_fraction is not None:
            raise ValueError("Cannot specify both target_size and target_fraction")
        if target_size and target_size < 0:
            raise ValueError("target_size must be non-negative")
        if target_fraction and (target_fraction < 0 or target_fraction > 1):
            raise ValueError("target_fraction must be between 0 and 1")

        bytes_reclaimed = 0
        paths = {}
        total_size = 0
        temp_size = 0
        for root, _, files in os.walk(self._cache_dir):
            for file in files:
                try:
                    path = os.path.join(root, file)
                    stat = os.stat(path)

                    if file.startswith(ArtifactsCache._TMP_PREFIX):
                        if remove_temp:
                            os.remove(path)
                            bytes_reclaimed += stat.st_size
                        else:
                            temp_size += stat.st_size
                            total_size += stat.st_size
                        continue
                except OSError:
                    continue
                paths[path] = stat
                total_size += stat.st_size

        if target_fraction is not None:
            target_size = int(total_size * target_fraction)
        assert target_size is not None

        if temp_size:
            wandb.termwarn(
                f"Cache contains {util.to_human_size(temp_size)} of temporary files. "
                "Run `wandb artifact cleanup --remove-temp` to remove them."
            )

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

        if total_size > target_size:
            wandb.termerror(
                f"Failed to reclaim enough space in {self._cache_dir}. Try running"
                " `wandb artifact cleanup --remove-temp` to remove temporary files."
            )

        return bytes_reclaimed

    def _reserve_space(self, path: StrPath, size: int) -> None:
        """If a `size` write would exceed disk space, remove cached items to make space.

        Raises:
            OSError: If there is not enough space to write `size` bytes, even after
                removing cached items.
        """
        # Get the most recent parent that exists.
        path = os.path.abspath(path)
        while not os.path.exists(os.path.dirname(path)):
            path = os.path.dirname(path)
        _, _, free = shutil.disk_usage(os.path.dirname(path))
        if free > size:
            return

        term.termwarn("Cache size exceeded. Attempting to reclaim space...")
        self.cleanup(target_fraction=0.5)
        _, _, free = shutil.disk_usage(os.path.dirname(path))
        if free > size:
            return

        self.cleanup(target_size=0)
        _, _, free = shutil.disk_usage(os.path.dirname(path))
        if free < size:
            raise OSError(errno.ENOSPC, f"Insufficient free space in {path}")

    def _cache_opener(self, path: StrPath, size: int) -> "Opener":
        @contextlib.contextmanager
        def helper(mode: str = "w") -> Generator[IO, None, None]:
            if "a" in mode:
                raise ValueError("Appending to cache files is not supported")

            self._reserve_space(path, size)
            dirname = os.path.dirname(path)
            mkdir_exists_ok(dirname)
            tmp_file = os.path.join(
                dirname, f"{ArtifactsCache._TMP_PREFIX}_{secrets.token_hex(8)}"
            )
            try:
                with util.fsync_open(tmp_file, mode=mode) as f:
                    yield f
            except Exception:
                # The write failed for whatever reason. Delete the temp file.
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass
                raise

            try:
                # Use replace where we can, as it implements an atomic
                # move on most platforms. If it doesn't exist, we have
                # to use rename which isn't atomic in all cases but there
                # isn't a better option.
                #
                # The atomic replace is important in the event multiple processes
                # attempt to write to / read from the cache at the same time. Each
                # writer firsts stages its writes to a temporary file in the cache.
                # Once it is finished, we issue an atomic replace operation to update
                # the cache. Although this can result in redundant downloads, this
                # guarantees that readers can NEVER read incomplete files from the
                # cache.
                #
                # IMPORTANT: Replace is NOT atomic across different filesystems. This why
                # it is critical that the temporary files sit directly in the cache --
                # they need to be on the same filesystem!
                os.replace(tmp_file, path)
            except AttributeError:
                os.rename(tmp_file, path)

        return helper


_artifacts_cache = None


def get_artifacts_cache() -> ArtifactsCache:
    global _artifacts_cache
    if _artifacts_cache is None:
        cache_dir = os.path.join(env.get_cache_dir(), "artifacts")
        _artifacts_cache = ArtifactsCache(cache_dir)
    return _artifacts_cache
