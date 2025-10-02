"""Artifact cache."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, ContextManager, Iterator, Protocol

import wandb
from wandb import env, util
from wandb.sdk.lib.filesystem import files_in
from wandb.sdk.lib.hashutil import B64MD5, ETag, b64_to_hex_id
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr


class Opener(Protocol):
    def __call__(self, mode: str = ...) -> ContextManager[IO]:
        pass


def artifacts_cache_dir() -> Path:
    """Get the artifacts cache directory."""
    return env.get_cache_dir() / "artifacts"


def _get_sys_umask_threadsafe() -> int:
    # Workaround to get the current system umask, since
    # - `os.umask()` isn't thread-safe
    # - we don't want to inadvertently change the umask of the current process
    # See: https://stackoverflow.com/questions/53227072/reading-umask-thread-safe
    umask_cmd = (sys.executable, "-c", "import os; print(os.umask(22))")
    return int(subprocess.check_output(umask_cmd))


class ArtifactFileCache:
    def __init__(self, cache_dir: StrPath) -> None:
        self._cache_dir = Path(cache_dir)
        self._obj_dir = self._cache_dir / "obj"
        self._temp_dir = self._cache_dir / "tmp"
        self._ensure_write_permissions()

        # NamedTemporaryFile sets the file mode to 600 [1], we reset to the default.
        # [1] https://stackoverflow.com/questions/10541760/can-i-set-the-umask-for-tempfile-namedtemporaryfile-in-python
        self._sys_umask = _get_sys_umask_threadsafe()

        self._override_cache_path: StrPath | None = None

    def check_md5_obj_path(
        self, b64_md5: B64MD5, size: int
    ) -> tuple[FilePathStr, bool, Opener]:
        # Check if we're using vs skipping the cache
        if self._override_cache_path is not None:
            skip_cache = True
            path = Path(self._override_cache_path)
        else:
            skip_cache = False
            hex_md5 = b64_to_hex_id(b64_md5)
            path = self._obj_dir / "md5" / hex_md5[:2] / hex_md5[2:]
        return self._check_or_create(path, size, skip_cache=skip_cache)

    # TODO(spencerpearson): this method at least needs its signature changed.
    # An ETag is not (necessarily) a checksum.
    def check_etag_obj_path(
        self,
        url: URIStr,
        etag: ETag,
        size: int,
    ) -> tuple[FilePathStr, bool, Opener]:
        # Check if we're using vs skipping the cache
        if self._override_cache_path is not None:
            skip_cache = True
            path = Path(self._override_cache_path)
        else:
            skip_cache = False
            hexhash = hashlib.sha256(
                hashlib.sha256(url.encode("utf-8")).digest()
                + hashlib.sha256(etag.encode("utf-8")).digest()
            ).hexdigest()
            path = self._obj_dir / "etag" / hexhash[:2] / hexhash[2:]
        return self._check_or_create(path, size, skip_cache=skip_cache)

    def _check_or_create(
        self, path: Path, size: int, skip_cache: bool = False
    ) -> tuple[FilePathStr, bool, Opener]:
        opener = self._opener(path, size, skip_cache=skip_cache)
        hit = path.is_file() and path.stat().st_size == size
        return FilePathStr(path), hit, opener

    def cleanup(
        self,
        target_size: int | None = None,
        remove_temp: bool = False,
        target_fraction: float | None = None,
    ) -> int:
        """Clean up the cache, removing the least recently used files first.

        Args:
            target_size: The target size of the cache in bytes. If the cache is larger
                than this, we will remove the least recently used files until the cache
                is smaller than this size.
            remove_temp: Whether to remove temporary files. Temporary files are files
                that are currently being written to the cache. If remove_temp is True,
                all temp files will be removed, regardless of the target_size or
                target_fraction.
            target_fraction: The target fraction of the cache to reclaim. If the cache
                is larger than this, we will remove the least recently used files until
                the cache is smaller than this fraction of its current size. It is an
                error to specify both target_size and target_fraction.

        Returns:
            The number of bytes reclaimed.
        """
        if target_size is None and target_fraction is None:
            # Default to clearing the entire cache.
            target_size = 0
        if target_size is not None and target_fraction is not None:
            raise ValueError("Cannot specify both target_size and target_fraction")
        if target_size is not None and target_size < 0:
            raise ValueError("target_size must be non-negative")
        if target_fraction is not None and (target_fraction < 0 or target_fraction > 1):
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
                " `wandb artifact cache cleanup --remove-temp` to remove temporary files."
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

        wandb.termwarn("Cache size exceeded. Attempting to reclaim space...")
        self.cleanup(target_fraction=0.5)
        if size <= self._free_space():
            return

        self.cleanup(target_size=0)
        if size > self._free_space():
            raise OSError(errno.ENOSPC, f"Insufficient free space in {self._cache_dir}")

    def _opener(self, path: Path, size: int, skip_cache: bool = False) -> Opener:
        @contextlib.contextmanager
        def atomic_open(mode: str = "w") -> Iterator[IO]:
            if "a" in mode:
                raise ValueError("Appending to cache files is not supported")

            if skip_cache:
                # We skip the cache, but we'll still need an intermediate, temporary file to ensure atomicity.
                # Put the temp file in the same root as the destination file in an attempt to avoid moving/copying
                # across filesystems.
                temp_dir = path.parent
            else:
                self._reserve_space(size)
                temp_dir = self._temp_dir

            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = NamedTemporaryFile(dir=temp_dir, mode=mode, delete=False)
            try:
                yield temp_file
                temp_file.close()
                os.chmod(temp_file.name, 0o666 & ~self._sys_umask)
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp_file.name, path)
            except Exception:
                os.remove(temp_file.name)
                raise

        return atomic_open

    def _ensure_write_permissions(self) -> None:
        """Raise an error if we cannot write to the cache directory."""
        try:
            self._temp_dir.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self._temp_dir) as f:
                f.write(b"wandb")
        except PermissionError as e:
            raise PermissionError(
                f"Unable to write to {self._cache_dir}. "
                "Ensure that the current user has write permissions."
            ) from e


# Memo `ArtifactFileCache` instances while avoiding reliance on global
# variable(s).  Notes:
# - @lru_cache should be thread-safe.
# - We don't memoize `get_artifact_file_cache` directly, as the cache_dir
#   may change at runtime.  This is likely rare in practice, though.
@lru_cache(maxsize=1)
def _build_artifact_file_cache(cache_dir: StrPath) -> ArtifactFileCache:
    return ArtifactFileCache(cache_dir)


def get_artifact_file_cache() -> ArtifactFileCache:
    return _build_artifact_file_cache(artifacts_cache_dir())
