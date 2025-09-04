"""Artifact manifest entry."""

# Older-style type annotations required for Pydantic v1 / python 3.8 compatibility.
# ruff: noqa: UP006, UP007, UP045

from __future__ import annotations

import concurrent.futures
import logging
import os
from os.path import getsize
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Final, Optional, Union
from urllib.parse import urlparse

from pydantic import Field
from typing_extensions import Annotated, Self, TypedDict, deprecated

from wandb._pydantic import field_validator, model_validator
from wandb.proto.wandb_deprecated import Deprecated
from wandb.sdk.lib.deprecate import deprecate
from wandb.sdk.lib.filesystem import copy_or_overwrite_changed
from wandb.sdk.lib.hashutil import (
    B64MD5,
    ETag,
    b64_to_hex_id,
    hex_to_b64_id,
    md5_file_b64,
)
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, URIStr

from ._base_model import ArtifactsBase

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from typing_extensions import TypedDict

    from .artifact import Artifact

    class ArtifactManifestEntryDict(TypedDict, total=False):
        path: str
        digest: str
        skip_cache: bool
        ref: str
        birthArtifactID: str
        size: int
        extra: dict
        local_path: str


_WB_ARTIFACT_SCHEME: Final[str] = "wandb-artifact"


class ArtifactManifestEntry(ArtifactsBase):
    """A single entry in an artifact manifest."""

    path: LogicalPath
    digest: Union[B64MD5, ETag, URIStr, FilePathStr]
    ref: Union[URIStr, FilePathStr, None] = None
    birth_artifact_id: Annotated[Optional[str], Field(alias="birthArtifactID")] = None
    size: Optional[int] = None
    extra: Dict[str, Any] = Field(default_factory=dict)
    local_path: Optional[str] = None

    skip_cache: bool = False

    # Note: Pydantic considers these private attributes and excludes them from
    # validation and equality logic.
    _parent_artifact: Optional[Artifact] = None
    _download_url: Optional[str] = None

    @field_validator("path", mode="before")
    def _validate_path(cls, v: Any) -> LogicalPath:
        return LogicalPath(v)

    @field_validator("local_path", mode="before")
    def _validate_local_path(cls, v: Any) -> str | None:
        return str(v) if v else None  # Apparently required to convert PosixPath to str

    @model_validator(mode="after")
    def _infer_size_from_local_path(self) -> Self:
        if (self.size is None) and self.local_path:
            self.size = getsize(self.local_path)
        return self

    def __repr__(self) -> str:
        displayed = self.model_dump(by_alias=False, exclude_none=True)
        # To maintain prior behavior, omit `extra` if empty.
        if not displayed.get("extra"):
            displayed.pop("extra", None)
        return f"{type(self).__name__}({', '.join(f'{k!s}={v!r}' for k, v in displayed.items())})"

    _NAME_DEPRECATED_MSG: ClassVar[str] = (
        "ArtifactManifestEntry.name is deprecated, use .path instead."
    )

    @property
    @deprecated(_NAME_DEPRECATED_MSG)
    def name(self) -> LogicalPath:
        """Deprecated; use `path` instead."""
        deprecate(
            field_name=Deprecated.artifactmanifestentry__name,
            warning_message=self._NAME_DEPRECATED_MSG,
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
        multipart: bool | None = None,
    ) -> FilePathStr:
        """Download this artifact entry to the specified root path.

        Args:
            root: (str, optional) The root path in which to download this
                artifact entry. Defaults to the artifact's root.

        Returns:
            (str): The path of the downloaded artifact entry.
        """
        if (artifact := self._parent_artifact) is None:
            raise NotImplementedError

        rootdir = root or artifact._default_root()
        artifact._add_download_root(rootdir)
        dest_path = os.path.join(rootdir, Path(self.path))

        # Skip checking the cache (and possibly downloading) if the file already exists
        # and has the digest we're expecting.
        try:
            md5_hash = md5_file_b64(dest_path)
        except (FileNotFoundError, IsADirectoryError):
            logger.debug(f"unable to find {dest_path}, skip searching for file")
        else:
            if self.digest == md5_hash:
                return FilePathStr(dest_path)

        # Override the target cache path if skipping the cache.
        overridden_cache_path = dest_path if skip_cache else None
        if self.ref is None:
            cache_path = artifact.manifest.storage_policy.load_file(
                artifact,
                self,
                dest_path=overridden_cache_path,
                executor=executor,
                multipart=multipart,
            )
        else:
            cache_path = artifact.manifest.storage_policy.load_reference(
                self, local=True, dest_path=overridden_cache_path
            )

        return FilePathStr(
            overridden_cache_path or copy_or_overwrite_changed(cache_path, dest_path)
        )

    def ref_target(self) -> FilePathStr | URIStr:
        """Get the reference URL that is targeted by this artifact entry.

        Returns:
            (str): The reference URL of this artifact entry.

        Raises:
            ValueError: If this artifact entry was not a reference.
        """
        if self.ref is None:
            raise ValueError("Only reference entries support ref_target().")
        if (artifact := self._parent_artifact) is None:
            return self.ref
        return artifact.manifest.storage_policy.load_reference(self, local=False)

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
        if (artifact := self._parent_artifact) is None:
            raise ValueError("Parent artifact is not set")
        if (artifact_id := artifact.id) is None:
            raise ValueError("Parent artifact ID is not set")
        return f"{_WB_ARTIFACT_SCHEME}://{b64_to_hex_id(artifact_id)}/{self.path}"

    def to_json(self) -> ArtifactManifestEntryDict:
        # NOTE: This method is misleadingly named, as it doesn't formally export
        # to JSON (i.e. a serialized JSON string), but rather a Python in-memory
        # dict.  The original name is kept for continuity, but consider deprecating.
        return self.model_dump(exclude_none=True)  # type: ignore[return-value]

    def _is_artifact_reference(self) -> bool:
        return bool(self.ref and urlparse(self.ref).scheme == _WB_ARTIFACT_SCHEME)

    def _referenced_artifact_id(self) -> str | None:
        if not self._is_artifact_reference():
            return None
        return hex_to_b64_id(urlparse(self.ref).netloc)
