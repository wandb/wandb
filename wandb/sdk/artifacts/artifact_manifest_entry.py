"""Artifact manifest entry."""
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Union

from wandb.sdk.lib.hashutil import B64MD5, ETag
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact as ArtifactInterface


class ArtifactManifestEntry:
    """A single entry in an artifact manifest."""

    path: LogicalPath
    digest: Union[B64MD5, URIStr, FilePathStr, ETag]
    ref: Optional[Union[FilePathStr, URIStr]]
    birth_artifact_id: Optional[str]
    size: Optional[int]
    extra: Dict
    local_path: Optional[str]

    def __init__(
        self,
        path: StrPath,
        digest: Union[B64MD5, URIStr, FilePathStr, ETag],
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

    def parent_artifact(self) -> "ArtifactInterface":
        """Get the artifact to which this artifact entry belongs.

        Returns:
            (Artifact): The parent artifact
        """
        raise NotImplementedError

    def download(self, root: Optional[str] = None) -> FilePathStr:
        """Download this artifact entry to the specified root path.

        Arguments:
            root: (str, optional) The root path in which to download this
                artifact entry. Defaults to the artifact's root.

        Returns:
            (str): The path of the downloaded artifact entry.
        """
        raise NotImplementedError

    def ref_target(self) -> Union[FilePathStr, URIStr]:
        """Get the reference URL that is targeted by this artifact entry.

        Returns:
            (str): The reference URL of this artifact entry.

        Raises:
            ValueError: If this artifact entry was not a reference.
        """
        if self.ref is None:
            raise ValueError("Only reference entries support ref_target().")
        return self.ref

    def ref_url(self) -> str:
        """Get a URL to this artifact entry.

        These URLs can be referenced by another artifact.

        Returns:
            (str): A URL representing this artifact entry.

        Examples:
            Basic usage
            ```
            ref_url = source_artifact.get_path('file.txt').ref_url()
            derived_artifact.add_reference(ref_url)
            ```
        """
        raise NotImplementedError
