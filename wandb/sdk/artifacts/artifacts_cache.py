"""Artifact cache."""
import contextlib
import errno
import hashlib
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, TYPE_CHECKING, ContextManager, Generator, Optional, Tuple

import wandb
from wandb import env, util
from wandb.errors import term
from wandb.sdk.lib.filesystem import files_in
from wandb.sdk.lib.hashutil import B64MD5, ETag, b64_to_hex_id
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    import sys

    if sys.version_info >= (3, 8):
        from typing import Protocol
    else:
        from typing_extensions import Protocol

    class Opener(Protocol):
        def __call__(self, mode: str = ...) -> ContextManager[IO]:
            pass


class ArtifactsCache:
    def __init__(self, cache_dir: StrPath) -> None:
        self._cache_dir = Path(cache_dir)
        self._obj_dir = self._cache_dir / "obj"
        self._temp_dir = self._cache_dir / "tmp"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def check_md5_obj_path(
        self, b64_md5: B64MD5, size: int
    ) -> Tuple[FilePathStr, bool, "Opener"]:
        hex_md5 = b64_to_hex_id(b64_md5)
        path = self._obj_dir / "md5" / hex_md5[:2] / hex_md5[2:]
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
        path = self._obj_dir / "etag" / hexhash[:2] / hexhash[2:]
        return self._check_or_create(path, size)

    def _check_or_create(
        self, path: Path, size: int
    ) -> Tuple[FilePathStr, bool, "Opener"]:
        opener = self._cache_opener(path, size)
        hit = path.is_file() and path.stat().st_size == size
        return FilePathStr(str(path)), hit, opener

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
        total_size = 0
        temp_size = 0

        # Remove all temporary files if requested. Otherwise sum their size.
        for entry in files_in(self._temp_dir):
            size = entry.stat().st_size
            total_size += size
            if remove_temp:
                try:
                    os.remove(entry.path)
                    bytes_reclaimed += size
                except OSError:
                    pass
            else:
                temp_size += size
        if temp_size:
            wandb.termwarn(
                f"Cache contains {util.to_human_size(temp_size)} of temporary files. "
                "Run `wandb artifact cleanup --remove-temp` to remove them."
            )

        entries = []
        for file_entry in files_in(self._obj_dir):
            total_size += file_entry.stat().st_size
            entries.append(file_entry)

        if target_fraction is not None:
            target_size = int(total_size * target_fraction)
        assert target_size is not None

        for entry in sorted(entries, key=lambda x: x.stat().st_atime):
            if total_size <= target_size:
                return bytes_reclaimed
            try:
                os.remove(entry.path)
            except OSError:
                pass
            total_size -= entry.stat().st_size
            bytes_reclaimed += entry.stat().st_size

        if total_size > target_size:
            wandb.termerror(
                f"Failed to reclaim enough space in {self._cache_dir}. Try running"
                " `wandb artifact cleanup --remove-temp` to remove temporary files."
            )

        return bytes_reclaimed

    def _free_space(self) -> int:
        """Return the number of bytes of free space in the cache directory."""
        return shutil.disk_usage(self._cache_dir)[2]

    def _reserve_space(self, size: int) -> None:
        """If a `size` write would exceed disk space, remove cached items to make space.

        Raises:
            OSError: If there is not enough space to write `size` bytes, even after
                removing cached items.
        """
        if size <= self._free_space():
            return

        term.termwarn("Cache size exceeded. Attempting to reclaim space...")
        self.cleanup(target_fraction=0.5)
        if size <= self._free_space():
            return

        self.cleanup(target_size=0)
        if size > self._free_space():
            raise OSError(errno.ENOSPC, f"Insufficient free space in {self._cache_dir}")

    def _cache_opener(self, path: Path, size: int) -> "Opener":
        @contextlib.contextmanager
        def helper(mode: str = "w") -> Generator[IO, None, None]:
            if "a" in mode:
                raise ValueError("Appending to cache files is not supported")

            self._reserve_space(size)
            temp_file = NamedTemporaryFile(dir=self._temp_dir, mode=mode, delete=False)
            try:
                yield temp_file
                temp_file.close()
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp_file.name, path)
            except Exception:
                os.remove(temp_file.name)
                raise

        return helper


_artifacts_cache = None


def get_artifacts_cache() -> ArtifactsCache:
    global _artifacts_cache
    if _artifacts_cache is None:
        _artifacts_cache = ArtifactsCache(env.get_cache_dir() / "artifacts")
    return _artifacts_cache
