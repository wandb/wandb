"""Artifact cache."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
from collections import deque
from contextlib import contextmanager, suppress
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from shutil import disk_usage
from tempfile import NamedTemporaryFile
from typing import IO, Any, ContextManager, Iterator, Protocol, runtime_checkable

from pydantic import ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Self

import wandb
from wandb import env
from wandb.sdk.artifacts._base_model import ArtifactsBase
from wandb.sdk.lib.filesystem import files_in
from wandb.sdk.lib.hashutil import B64MD5, ETag, b64_to_hex_id
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr
from wandb.util import to_human_size


@runtime_checkable
class Opener(Protocol):
    def __call__(self, mode: str = ...) -> ContextManager[IO]:
        pass


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


@pydantic_dataclass(frozen=True, config=ConfigDict(arbitrary_types_allowed=True))
class _CacheCheckResult:
    """An internal wrapper for the result of checking (or creating) a file path in the artifact file cache."""

    path: FilePathStr
    hit: bool
    open: Opener


class _ArtifactFileCacheConfig(ArtifactsBase):
    cache_dir: Path
    obj_dir: Path
    temp_dir: Path

    # NamedTemporaryFile sets the file mode to 600 [1], we reset to the default.
    # [1] https://stackoverflow.com/questions/10541760/can-i-set-the-umask-for-tempfile-namedtemporaryfile-in-python
    sys_umask: int = Field(default_factory=_get_sys_umask_threadsafe, init=False)

    @model_validator(mode="before")
    @classmethod
    def _set_default_subdirs(cls, data: Any) -> Any:
        if isinstance(data, dict) and (root := data.get("cache_dir")):
            return {
                "obj_dir": root / "obj",
                "temp_dir": root / "tmp",
                **data,  # This comes last to avoid overriding obj_dir/temp_dir if they're already set
            }
        return data

    @model_validator(mode="after")
    def _ensure_write_permissions(self) -> Self:
        """Raise an error if we cannot write to the cache directory."""
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.temp_dir) as f:
                f.write(b"wandb")
        except PermissionError as e:
            raise PermissionError(
                f"Unable to write to {self.cache_dir}. "
                "Ensure that the current user has write permissions."
            ) from e
        return self


class ArtifactFileCache:
    _config: _ArtifactFileCacheConfig
    _override_cache_path: StrPath | None

    def __init__(self, cache_dir: StrPath) -> None:
        self._config = _ArtifactFileCacheConfig(cache_dir=cache_dir)
        self._override_cache_path: StrPath | None = None

    def check_md5_obj_path(self, b64_md5: B64MD5, size: int) -> _CacheCheckResult:
        # Check if we're using vs skipping the cache
        if skip_cache := (self._override_cache_path is not None):
            path = Path(self._override_cache_path)
        else:
            hex_md5 = b64_to_hex_id(b64_md5)
            path = self._config.obj_dir / "md5" / hex_md5[:2] / hex_md5[2:]
        return self._check_or_create(path, size, skip_cache=skip_cache)

    # TODO(spencerpearson): this method at least needs its signature changed.
    # An ETag is not (necessarily) a checksum.
    def check_etag_obj_path(
        self, url: URIStr, etag: ETag, size: int
    ) -> _CacheCheckResult:
        # Check if we're using vs skipping the cache
        if skip_cache := (self._override_cache_path is not None):
            path = Path(self._override_cache_path)
        else:
            hexhash = sha256(
                sha256(url.encode("utf-8")).digest()
                + sha256(etag.encode("utf-8")).digest()
            ).hexdigest()
            path = self._config.obj_dir / "etag" / hexhash[:2] / hexhash[2:]
        return self._check_or_create(path, size, skip_cache=skip_cache)

    def _check_or_create(
        self, path: Path, size: int, skip_cache: bool = False
    ) -> _CacheCheckResult:
        opener = self._opener(path, size, skip_cache=skip_cache)
        hit = path.is_file() and path.stat().st_size == size
        return _CacheCheckResult(path=FilePathStr(path), hit=hit, open=opener)

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
        if target_fraction is not None and not (0 <= target_fraction <= 1):
            raise ValueError("target_fraction must be between 0 and 1")

        reclaimed: int = 0  # Bytes reclaimed so far

        # Remove all temporary files if requested. Otherwise sum their size.
        if remove_temp:
            temp_dir_size = 0
            for entry in files_in(self._config.temp_dir):
                temp_dir_size += entry.stat().st_size
                reclaimed += _maybe_reclaim(entry)
        else:
            if temp_dir_size := sum(
                entry.stat().st_size for entry in files_in(self._config.temp_dir)
            ):
                wandb.termwarn(
                    f"Cache contains {to_human_size(temp_dir_size)} of temporary files. "
                    "Run `wandb artifact cleanup --remove-temp` to remove them."
                )

        # Go through obj_dir, preferring to remove the least-recently accessed files first.
        obj_dir_entries: deque[os.DirEntry] = deque(
            sorted(
                files_in(self._config.obj_dir),
                key=lambda x: x.stat().st_atime,
            )
        )
        obj_dir_size = sum(entry.stat().st_size for entry in obj_dir_entries)

        total_size = temp_dir_size + obj_dir_size  # Total size of files in the cache

        if target_fraction is not None:
            target_size = int(total_size * target_fraction)

        assert target_size is not None

        target_reclaimed = total_size - target_size

        # Reclaim space until we're under the target size.
        while (reclaimed < target_reclaimed) and obj_dir_entries:
            entry = obj_dir_entries.popleft()
            reclaimed += _maybe_reclaim(entry)

        # Check if we've reclaimed enough space.
        if reclaimed < target_reclaimed:
            wandb.termerror(
                f"Failed to reclaim enough space in {self._config.cache_dir}. Try running"
                " `wandb artifact cache cleanup --remove-temp` to remove temporary files."
            )

        return reclaimed

    def _reserve_space(self, size: int) -> None:
        """If a `size` write would exceed disk space, remove cached items to make space.

        Raises:
            OSError: If there is not enough space to write `size` bytes, even after
                removing cached items.
        """
        cache_dir = self._config.cache_dir

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
                # We skip the cache, but we'll still need an intermediate, temporary file to ensure atomicity.
                # Put the temp file in the same root as the destination file in an attempt to avoid moving/copying
                # across filesystems.
                temp_dir = path.parent
            else:
                self._reserve_space(size)
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
                os.remove(temp_file.name)
                raise

        return atomic_open


# Memo `ArtifactFileCache` instances while avoiding reliance on global
# variable(s).  Notes:
# - @lru_cache should be thread-safe.
# - We don't memoize `get_artifact_file_cache` directly, as the cache_dir
#   may change at runtime.  This is likely rare in practice, though.
@lru_cache(maxsize=1)
def _build_artifact_file_cache(cache_dir: StrPath) -> ArtifactFileCache:
    return ArtifactFileCache(cache_dir)


def get_artifact_file_cache() -> ArtifactFileCache:
    return _build_artifact_file_cache(env.get_cache_dir() / "artifacts")
