"""Artifact manifest entry."""

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Union
from urllib.parse import urlparse

from wandb.sdk.lib import filesystem
from wandb.sdk.lib.deprecate import Deprecated, deprecate
from wandb.sdk.lib.hashutil import (
    B64MD5,
    ETag,
    b64_to_hex_id,
    hex_to_b64_id,
    md5_file_b64,
)
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from typing_extensions import TypedDict

    from wandb.sdk.artifacts.artifact import Artifact

    class ArtifactManifestEntryDict(TypedDict, total=False):
        path: str
        digest: str
        skip_cache: bool
        ref: str
        birthArtifactID: str
        size: int
        extra: Dict
        local_path: str


class ArtifactManifestEntry:
    """A single entry in an artifact manifest."""

    path: LogicalPath
    digest: Union[B64MD5, URIStr, FilePathStr, ETag]
    skip_cache: bool
    ref: Optional[Union[FilePathStr, URIStr]]
    birth_artifact_id: Optional[str]
    size: Optional[int]
    extra: Dict
    local_path: Optional[str]

    _parent_artifact: Optional["Artifact"] = None
    _download_url: Optional[str] = None

    def __init__(
        self,
        path: StrPath,
        digest: Union[B64MD5, URIStr, FilePathStr, ETag],
        skip_cache: Optional[bool] = False,
        ref: Optional[Union[FilePathStr, URIStr]] = None,
        birth_artifact_id: Optional[str] = None,
        size: Optional[int] = None,
        extra: Optional[Dict] = None,
        local_path: Optional[StrPath] = None,
    ) -> None:
        self.path = LogicalPath(path)
        self.digest = digest
        self.ref = ref
        self.birth_artifact_id = birth_artifact_id
        self.size = size
        self.extra = extra or {}
        self.local_path = str(local_path) if local_path else None
        if self.local_path and self.size is None:
            self.size = Path(self.local_path).stat().st_size
        self.skip_cache = skip_cache or False

    def __repr__(self) -> str:
        cls = self.__class__.__name__
        ref = f", ref={self.ref!r}" if self.ref is not None else ""
        birth_artifact_id = (
            f", birth_artifact_id={self.birth_artifact_id!r}"
            if self.birth_artifact_id is not None
            else ""
        )
        size = f", size={self.size}" if self.size is not None else ""
        extra = f", extra={json.dumps(self.extra)}" if self.extra else ""
        local_path = f", local_path={self.local_path!r}" if self.local_path else ""
        skip_cache = f", skip_cache={self.skip_cache}"
        others = ref + birth_artifact_id + size + extra + local_path + skip_cache
        return f"{cls}(path={self.path!r}, digest={self.digest!r}{others})"

    def __eq__(self, other: object) -> bool:
        """Strict equality, comparing all public fields.

        ArtifactManifestEntries for the same file may not compare equal if they were
        added in different ways or created for different parent artifacts.
        """
        if not isinstance(other, ArtifactManifestEntry):
            return False
        return (
            self.path == other.path
            and self.digest == other.digest
            and self.ref == other.ref
            and self.birth_artifact_id == other.birth_artifact_id
            and self.size == other.size
            and self.extra == other.extra
            and self.local_path == other.local_path
            and self.skip_cache == other.skip_cache
        )

    @property
    def name(self) -> LogicalPath:
        """Deprecated; use `path` instead."""
        deprecate(
            field_name=Deprecated.artifactmanifestentry__name,
            warning_message="ArtifactManifestEntry.name is deprecated, use .path instead.",
        )
        return self.path

    def parent_artifact(self) -> "Artifact":
        """Get the artifact to which this artifact entry belongs.

        Returns:
            (PublicArtifact): The parent artifact
        """
        if self._parent_artifact is None:
            raise NotImplementedError
        return self._parent_artifact

    def download(
        self, root: Optional[str] = None, skip_cache: Optional[bool] = None
    ) -> FilePathStr:
        """Download this artifact entry to the specified root path.

        Arguments:
            root: (str, optional) The root path in which to download this
                artifact entry. Defaults to the artifact's root.

        Returns:
            (str): The path of the downloaded artifact entry.
        """
        if self._parent_artifact is None:
            raise NotImplementedError

        root = root or self._parent_artifact._default_root()
        self._parent_artifact._add_download_root(root)
        path = str(Path(self.path))
        dest_path = os.path.join(root, path)

        if skip_cache:
            override_cache_path = dest_path
        else:
            override_cache_path = None

        # Skip checking the cache (and possibly downloading) if the file already exists
        # and has the digest we're expecting.
        try:
            md5_hash = md5_file_b64(dest_path)
        except (FileNotFoundError, IsADirectoryError):
            logger.debug(f"unable to find {dest_path}, skip searching for file")
        else:
            if self.digest == md5_hash:
                return FilePathStr(dest_path)

        if self.ref is not None:
            cache_path = self._parent_artifact.manifest.storage_policy.load_reference(
                self, local=True, dest_path=override_cache_path
            )
        else:
            cache_path = self._parent_artifact.manifest.storage_policy.load_file(
                self._parent_artifact, self, dest_path=override_cache_path
            )

        if skip_cache:
            return FilePathStr(dest_path)
        else:
            return FilePathStr(
                str(filesystem.copy_or_overwrite_changed(cache_path, dest_path))
            )

    def ref_target(self) -> Union[FilePathStr, URIStr]:
        """Get the reference URL that is targeted by this artifact entry.

        Returns:
            (str): The reference URL of this artifact entry.

        Raises:
            ValueError: If this artifact entry was not a reference.
        """
        if self.ref is None:
            raise ValueError("Only reference entries support ref_target().")
        if self._parent_artifact is None:
            return self.ref
        return self._parent_artifact.manifest.storage_policy.load_reference(
            self._parent_artifact.manifest.entries[self.path], local=False
        )

    def ref_url(self) -> str:
        """Get a URL to this artifact entry.

        These URLs can be referenced by another artifact.

        Returns:
            (str): A URL representing this artifact entry.

        Examples:
            Basic usage
            ```
            ref_url = source_artifact.get_entry('file.txt').ref_url()
            derived_artifact.add_reference(ref_url)
            ```
        """
        if self._parent_artifact is None:
            raise NotImplementedError
        assert self._parent_artifact.id is not None
        return (
            "wandb-artifact://"
            + b64_to_hex_id(B64MD5(self._parent_artifact.id))
            + "/"
            + self.path
        )

    def to_json(self) -> "ArtifactManifestEntryDict":
        contents: ArtifactManifestEntryDict = {
            "path": self.path,
            "digest": self.digest,
        }
        if self.size is not None:
            contents["size"] = self.size
        if self.ref:
            contents["ref"] = self.ref
        if self.birth_artifact_id:
            contents["birthArtifactID"] = self.birth_artifact_id
        if self.local_path:
            contents["local_path"] = self.local_path
        if self.skip_cache:
            contents["skip_cache"] = self.skip_cache
        if self.extra:
            contents["extra"] = self.extra
        return contents

    def _is_artifact_reference(self) -> bool:
        return self.ref is not None and urlparse(self.ref).scheme == "wandb-artifact"

    def _referenced_artifact_id(self) -> Optional[str]:
        if not self._is_artifact_reference():
            return None
        return hex_to_b64_id(urlparse(self.ref).netloc)
