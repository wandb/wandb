"""Storage handler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from wandb.sdk.lib.paths import FilePathStr, URIStr

if TYPE_CHECKING:
    from urllib.parse import ParseResult

    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry

DEFAULT_MAX_OBJECTS = 10**7


class StorageHandler:
    def can_handle(self, parsed_url: ParseResult) -> bool:
        """Checks whether this handler can handle the given url.

        Returns:
            Whether this handler can handle the given url.
        """
        raise NotImplementedError

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        """Load a file or directory given the corresponding index entry.

        Args:
            manifest_entry: The index entry to load
            local: Whether to load the file locally or not

        Returns:
            A path to the file represented by `index_entry`
        """
        raise NotImplementedError

    def store_path(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: str | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> Sequence[ArtifactManifestEntry]:
        """Store the file or directory at the given path to the specified artifact.

        Args:
            path: The path to store
            name: If specified, the logical name that should map to `path`
            checksum: Whether to compute the checksum of the file
            max_objects: The maximum number of objects to store

        Returns:
            A list of manifest entries to store within the artifact
        """
        raise NotImplementedError
