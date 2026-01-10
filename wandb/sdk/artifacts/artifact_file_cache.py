"""Artifact cache."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
from contextlib import contextmanager, suppress
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from shutil import disk_usage
from tempfile import NamedTemporaryFile
from typing import IO, ContextManager, Iterator, Protocol, runtime_checkable

from pydantic import Field, model_validator
from typing_extensions import Self

import wandb
from wandb import env
from wandb.sdk.lib.filesystem import files_in
from wandb.sdk.lib.hashutil import B64MD5, ETag, b64_to_hex_id
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

from ._models.base_model import ArtifactsBase


@runtime_checkable
class Opener(Protocol):
    def __call__(self, mode: str = ...) -> ContextManager[IO]: ...


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


def _maybe_reclaim(entry: os.DirEntry) -> int:
    """Attempt to remove an entry from the cache, returning the number of bytes reclaimed if successful, otherwise 0."""
    # DirEntry.stat() is cached, but fetch before deleting to be safe
    size = entry.stat().st_size
    with suppress(OSError):
        os.remove(entry)
        return size
    return 0


def _is_cache_hit(path: Path, size: int) -> bool:
    # Note: this was refactored out of existing logic which did indeed
    # just check for matching file sizes to identify cache hits.
    return path.is_file() and path.stat().st_size == size


class _ArtifactFileCacheManager(ArtifactsBase):
    cache_dir: Path

    # NamedTemporaryFile sets the file mode to 600 [1], we reset to the default.
    # [1] https://stackoverflow.com/questions/10541760/can-i-set-the-umask-for-tempfile-namedtemporaryfile-in-python
    sys_umask: int = Field(default_factory=_get_sys_umask_threadsafe, frozen=True)

    @property
    def temp_dir(self) -> Path:
        return self.cache_dir / "tmp"

    @property
    def obj_dir(self) -> Path:
        return self.cache_dir / "obj"

    def temp_files(self) -> Iterator[os.DirEntry]:
        """Yields from the temporary files in the cache directory."""
        yield from files_in(self.temp_dir)

    def obj_files(self) -> Iterator[os.DirEntry]:
        """Yields from the object files in the cache directory."""
        yield from files_in(self.obj_dir)

    @model_validator(mode="after")
    def _ensure_write_permissions(self) -> Self:
        """Raise an error if we cannot write to the cache directory."""
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.temp_dir) as f:
                f.write(b"wandb")
        except PermissionError as e:
            msg = f"Unable to write to {self.cache_dir}. Ensure that current user has write permissions."
            raise PermissionError(msg) from e
        return self


class ArtifactFileCache:
    def __init__(self, cache_dir: StrPath) -> None:
        self._config = _ArtifactFileCacheManager(cache_dir=cache_dir)
        self._override_cache_path: StrPath | None = None

    def check_md5_obj_path(
        self, b64_md5: B64MD5, size: int
    ) -> tuple[FilePathStr, bool, Opener]:
        # Check if we're using vs skipping the cache
        if skip_cache := (self._override_cache_path is not None):
            path = Path(self._override_cache_path)
        else:
            path = self._md5_cache_path(b64_md5)

        return (
            FilePathStr(path),
            path.is_file() and path.stat().st_size == size,
            self._opener(path, size, skip_cache=skip_cache),
        )

    def _md5_cache_path(self, b64_md5: B64MD5) -> Path:
        """Returns the designated file path for an MD5 hash in the cache."""
        hexhash = b64_to_hex_id(b64_md5)
        return self._config.obj_dir / "md5" / hexhash[:2] / hexhash[2:]

    # TODO(spencerpearson): this method at least needs its signature changed.
    # An ETag is not (necessarily) a checksum.
    def check_etag_obj_path(
        self, url: URIStr, etag: ETag, size: int
    ) -> tuple[FilePathStr, bool, Opener]:
        # Check if we're using vs skipping the cache
        if skip_cache := (self._override_cache_path is not None):
            path = Path(self._override_cache_path)
        else:
            path = self._etag_cache_path(url, etag)

        return (
            FilePathStr(path),
            _is_cache_hit(path, size=size),
            self._opener(path, size, skip_cache=skip_cache),
        )

    def _etag_cache_path(self, url: URIStr, etag: ETag) -> Path:
        """Returns the designated file path for an ETag in the cache."""
        encoded_parts = (url.encode("utf-8"), etag.encode("utf-8"))
        combined_digest = b"".join(sha256(b_part).digest() for b_part in encoded_parts)
        hexhash = sha256(combined_digest).hexdigest()
        return self._config.obj_dir / "etag" / hexhash[:2] / hexhash[2:]

    def _check_or_create(
        self, path: Path, size: int, skip_cache: bool = False
    ) -> tuple[FilePathStr, bool, Opener]:
        return (
            FilePathStr(path),
            _is_cache_hit(path, size=size),
            self._opener(path, size, skip_cache=skip_cache),
        )

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
        if (target_size is not None) and (target_fraction is not None):
            raise ValueError("Cannot specify both target_size and target_fraction")
        if (target_size is not None) and (target_fraction is not None):
            raise ValueError("Cannot specify both target_size and target_fraction")
        if (target_size is not None) and (target_size < 0):
            raise ValueError("target_size must be non-negative")
        if (target_fraction is not None) and not (0 <= target_fraction <= 1):
            raise ValueError("target_fraction must be between 0 and 1")

        # Some helper functions for iterating over DirEntry objects.
        def _atime(e: os.DirEntry) -> float:
            """Get the access time of a DirEntry."""
            return e.stat().st_atime

        def _size(e: os.DirEntry) -> int:
            """Get the size of a DirEntry."""
            return e.stat().st_size

        # Total file size in cache subdirectories
        temp_dir_size = sum(map(_size, self._config.temp_files()))
        obj_dir_size = sum(map(_size, self._config.obj_files()))
        total_size = temp_dir_size + obj_dir_size  # Total size of files in the cache

        if target_size is None and target_fraction is None:
            target_reclaimed = total_size  # Default to clearing the entire cache.
        elif (target_size is not None) and (target_fraction is None):
            target_reclaimed = total_size - target_size
        elif (target_size is None) and (target_fraction is not None):
            target_reclaimed = int(total_size * (1.0 - target_fraction))
        else:  # pragma: no cover
            # This should be unreachable, but mypy etc. aren't powerful enough to recognize this right now.
            raise RuntimeError(
                f"Invalid arguments to {nameof(self.cleanup)}, got: {target_size=}, {target_fraction=}"
            )

        # Remove all temporary files, if requested.
        reclaimed: int  # Bytes reclaimed so far
        if remove_temp:
            reclaimed = sum(_maybe_reclaim(f) for f in self._config.temp_files())
        else:
            reclaimed = 0
            if temp_dir_size:
                wandb.termwarn(
                    f"Cache contains {to_human_size(temp_dir_size)} of temporary files. "
                    "Run `wandb artifact cache cleanup --remove-temp` to remove them."
                )

        # Go through obj_dir, preferring to remove the least-recently accessed files first.
        # Reclaim space until we're under the target size.
        for entry in sorted(self._config.obj_files(), key=_atime):
            if reclaimed >= target_reclaimed:
                break
            reclaimed += _maybe_reclaim(entry)

        # Check if we've reclaimed enough space.
        if reclaimed < target_reclaimed:
            wandb.termerror(
                f"Failed to reclaim enough space in {self._config.cache_dir}. Try running"
                " `wandb artifact cache cleanup --remove-temp` to remove temporary files."
            )

        return reclaimed

    def _reserve_space(self, cache_dir: Path, size: int) -> None:
        """If a `size` write would exceed disk space, remove cached items to make space.

        Raises:
            OSError: If there is not enough space to write `size` bytes, even after
                removing cached items.
        """
        if size <= disk_usage(cache_dir).free:
            return

        wandb.termwarn("Cache size exceeded. Attempting to reclaim space...")
        self.cleanup(target_fraction=0.5)
        if size <= disk_usage(cache_dir).free:
            return

        self.cleanup(target_size=0)
        if size <= disk_usage(cache_dir).free:
            return

        raise OSError(errno.ENOSPC, f"Insufficient free space in {cache_dir}")

    def _opener(self, path: Path, size: int, skip_cache: bool = False) -> Opener:
        @contextmanager
        def atomic_open(mode: str = "w") -> Iterator[IO]:
            if "a" in mode:
                raise ValueError("Appending to cache files is not supported")

            if skip_cache:
                # Skip the cache but still use an intermediate temporary file to
                # ensure atomicity. Place the temp file in the same root as the
                # destination file to avoid cross-filesystem move/copy operations.
                temp_dir = path.parent
            else:
                self._reserve_space(self._config.cache_dir, size)
                temp_dir = self._config.temp_dir

            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = NamedTemporaryFile(dir=temp_dir, mode=mode, delete=False)
            try:
                yield temp_file
                temp_file.close()
                os.chmod(temp_file.name, 0o666 & ~self._config.sys_umask)
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp_file.name, path)
            except Exception:
                # Note: If os.replace was successful, the original temp_file be removed
                # by definition. This call is only necessary if os.replace is unsuccessful.
                os.remove(temp_file.name)
                raise

        return atomic_open


# Memoizes `ArtifactFileCache` instances while avoiding reliance on global
# variable(s).  Notes:
# - @lru_cache should be thread-safe.
# - We don't memoize `get_artifact_file_cache` directly, as the cache_dir
#   may change at runtime.  This is likely rare in practice, though.
@lru_cache(maxsize=1)
def _build_artifact_file_cache(cache_dir: StrPath) -> ArtifactFileCache:
    return ArtifactFileCache(cache_dir)


def get_artifact_file_cache() -> ArtifactFileCache:
    return _build_artifact_file_cache(artifacts_cache_dir())
