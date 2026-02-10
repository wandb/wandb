"""Artifact manifest entry."""

# Older-style type annotations required for Pydantic v1 / python 3.8 compatibility.
# ruff: noqa: UP006, UP007, UP035, UP045

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
from contextlib import suppress
from os.path import getsize
from typing import TYPE_CHECKING, Annotated, Any, Dict, Final, Optional, Union
from urllib.parse import urlparse

from pydantic import Field, NonNegativeInt
from typing_extensions import Self

from wandb._pydantic import field_validator, model_validator
from wandb._strutils import nameof
from wandb.proto.wandb_telemetry_pb2 import Deprecated
from wandb.sdk.lib.deprecation import warn_and_record_deprecation
from wandb.sdk.lib.filesystem import copy_or_overwrite_changed
from wandb.sdk.lib.hashutil import (
    B64MD5,
    ETag,
    b64_to_hex_id,
    hex_to_b64_id,
    md5_file_b64,
)
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, URIStr

from ._models.base_model import ArtifactsBase

if TYPE_CHECKING:
    from .artifact import Artifact


logger = logging.getLogger(__name__)


_WB_ARTIFACT_SCHEME: Final[str] = "wandb-artifact"


def _checksum_cache_path(file_path: str) -> str:
    """Get path for checksum in central cache directory."""
    from wandb.sdk.artifacts.artifact_file_cache import artifacts_cache_dir

    # Create a unique cache key based on the file's absolute path
    abs_path = os.path.abspath(file_path)
    path_hash = hashlib.sha256(abs_path.encode()).hexdigest()

    # Store in wandb cache directory under checksums subdirectory
    cache_dir = artifacts_cache_dir() / "checksums"
    cache_dir.mkdir(parents=True, exist_ok=True)

    return str(cache_dir / f"{path_hash}.checksum")


def _read_cached_checksum(file_path: str) -> str | None:
    """Read checksum from cache if it exists and is valid."""
    checksum_path = _checksum_cache_path(file_path)

    try:
        with open(file_path) as f, open(checksum_path) as f_checksum:
            if os.path.getmtime(f_checksum.name) < os.path.getmtime(f.name):
                # File was modified after checksum was written
                return None
            # Read and return the cached checksum
            return f_checksum.read().strip()
    except OSError:
        # File doesn't exist or couldn't be opened
        return None


def _write_cached_checksum(file_path: str, checksum: str) -> None:
    """Write checksum to cache directory."""
    checksum_path = _checksum_cache_path(file_path)
    try:
        with open(checksum_path, "w") as f:
            f.write(checksum)
    except OSError:
        # Non-critical failure, just log it
        logger.debug(f"Failed to write checksum cache for {file_path!r}")


class ArtifactManifestEntry(ArtifactsBase):
    """A single entry in an artifact manifest.

    External code should avoid instantiating this class directly.
    """

    path: LogicalPath

    digest: Union[B64MD5, ETag, URIStr, FilePathStr]
    ref: Union[URIStr, FilePathStr, None] = None
    birth_artifact_id: Annotated[Optional[str], Field(alias="birthArtifactID")] = None
    size: Optional[NonNegativeInt] = None
    extra: Dict[str, Any] = Field(default_factory=dict)
    local_path: Optional[str] = None

    skip_cache: bool = False

    # Note: Pydantic treats these as private attributes, omitting them from
    # validation and comparison logic.
    _parent_artifact: Optional[Artifact] = None
    _download_url: Optional[str] = None

    @field_validator("path", mode="before")
    def _validate_path(cls, v: Any) -> LogicalPath:
        """Coerce `path` to a LogicalPath.

        LogicalPath does not implement its own pydantic validator, and adding
        one for both pydantic V1 and V2 would add excessive boilerplate. Until
        we drop V1 support, coerce to LogicalPath in this field validator.
        """
        return LogicalPath(v)

    @field_validator("local_path", mode="before")
    def _validate_local_path(cls, v: Any) -> str | None:
        """Coerce `local_path` to a str. Necessary if the input is a `PosixPath`."""
        return str(v) if v else None

    @model_validator(mode="after")
    def _infer_size_from_local_path(self) -> Self:
        """If `size` isn't set, try to infer it from `local_path`."""
        if (self.size is None) and self.local_path:
            self.size = getsize(self.local_path)
        return self

    def __repr__(self) -> str:
        # For compatibility with prior behavior, don't display `extra` if it's empty
        exclude = None if self.extra else {"extra"}
        repr_dict = self.model_dump(by_alias=False, exclude_none=True, exclude=exclude)
        return f"{nameof(type(self))}({', '.join(f'{k}={v!r}' for k, v in repr_dict.items())})"

    @property
    def name(self) -> LogicalPath:
        """Deprecated; use `path` instead."""
        warn_and_record_deprecation(
            feature=Deprecated(artifactmanifestentry__name=True),
            message="ArtifactManifestEntry.name is deprecated, use .path instead.",
        )
        return self.path

    def parent_artifact(self) -> Artifact:
        """Get the artifact to which this artifact entry belongs.

        Returns:
            (PublicArtifact): The parent artifact
        """
        if self._parent_artifact is None:
            raise NotImplementedError
        return self._parent_artifact

    def download(
        self,
        root: str | None = None,
        skip_cache: bool | None = None,
        executor: concurrent.futures.Executor | None = None,
    ) -> FilePathStr:
        """Download this artifact entry to the specified root path.

        Args:
            root: (str, optional) The root path in which to download this
                artifact entry. Defaults to the artifact's root.

        Returns:
            (str): The path of the downloaded artifact entry.
        """
        artifact = self.parent_artifact()
        rootdir = artifact._add_download_root(root)
        dest_path = os.path.join(rootdir, self.path)

        # Skip checking the cache (and possibly downloading) if the file already exists
        # and has the digest we're expecting.

        # Fast integrity check using cached checksum from persistent cache
        with suppress(OSError):
            if self.digest == _read_cached_checksum(dest_path):
                return FilePathStr(dest_path)

        # Fallback to computing/caching the checksum hash
        try:
            md5_hash = md5_file_b64(dest_path)
        except (FileNotFoundError, IsADirectoryError):
            logger.debug(f"unable to find {dest_path!r}, skip searching for file")
        else:
            _write_cached_checksum(dest_path, md5_hash)
            if self.digest == md5_hash:
                return FilePathStr(dest_path)

        # Override the target cache path IF we're skipping the cache.
        # Note that `override_cache_path is None` <=> `skip_cache is False`.
        override_cache_path = FilePathStr(dest_path) if skip_cache else None
        storage_policy = artifact.manifest.storage_policy
        if self.ref is not None:
            cache_path = storage_policy.load_reference(
                self, local=True, dest_path=override_cache_path
            )
        else:
            cache_path = storage_policy.load_file(
                artifact, self, dest_path=override_cache_path, executor=executor
            )

        # Determine the final path
        final_path = FilePathStr(
            override_cache_path or copy_or_overwrite_changed(cache_path, dest_path)
        )

        # Cache the checksum for future downloads
        _write_cached_checksum(final_path, self.digest)

        return final_path

    def ref_target(self) -> FilePathStr | URIStr:
        """Get the reference URL that is targeted by this artifact entry.

        Returns:
            (str): The reference URL of this artifact entry.

        Raises:
            ValueError: If this artifact entry was not a reference.
        """
        if self.ref is None:
            raise ValueError("Only reference entries support ref_target().")
        if (parent_artifact := self._parent_artifact) is None:
            return self.ref
        return parent_artifact.manifest.storage_policy.load_reference(self, local=False)

    def ref_url(self) -> str:
        """Get a URL to this artifact entry.

        These URLs can be referenced by another artifact.

        Returns:
            (str): A URL representing this artifact entry.

        Examples:
            Basic usage
            ```
            ref_url = source_artifact.get_entry("file.txt").ref_url()
            derived_artifact.add_reference(ref_url)
            ```
        """
        if (parent_artifact := self.parent_artifact()) is None:
            raise ValueError("Parent artifact is not set")
        elif (parent_id := parent_artifact.id) is None:
            raise ValueError("Parent artifact ID is not set")
        return f"{_WB_ARTIFACT_SCHEME}://{b64_to_hex_id(parent_id)}/{self.path}"

    def to_json(self) -> dict[str, Any]:
        # NOTE: The method name `to_json` is a bit misleading, as this returns a
        # python dict, NOT a JSON string. The historical name is kept for continuity,
        # but consider deprecating this in favor of `BaseModel.model_dump()`.
        return self.model_dump(exclude_none=True)  # type: ignore[return-value]

    def _is_artifact_reference(self) -> bool:
        return self.ref is not None and urlparse(self.ref).scheme == _WB_ARTIFACT_SCHEME

    def _referenced_artifact_id(self) -> str | None:
        if not self._is_artifact_reference():
            return None
        return hex_to_b64_id(urlparse(self.ref).netloc)
