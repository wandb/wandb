"""WB local artifact storage handler."""
import os
from typing import TYPE_CHECKING, Optional, Sequence, Union

import wandb
from wandb import util
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifacts_cache import get_artifacts_cache
from wandb.sdk.artifacts.storage_handler import StorageHandler
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    from urllib.parse import ParseResult

    from wandb.sdk.artifacts.artifact import Artifact as ArtifactInterface


class WBLocalArtifactHandler(StorageHandler):
    """Handles loading and storing Artifact reference-type files."""

    def __init__(self) -> None:
        self._scheme = "wandb-client-artifact"
        self._cache = get_artifacts_cache()

    def can_handle(self, parsed_url: "ParseResult") -> bool:
        return parsed_url.scheme == self._scheme

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> Union[URIStr, FilePathStr]:
        raise NotImplementedError(
            "Should not be loading a path for an artifact entry with unresolved client id."
        )

    def store_path(
        self,
        artifact: "ArtifactInterface",
        path: Union[URIStr, FilePathStr],
        name: Optional[StrPath] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        """Store the file or directory at the given path within the specified artifact.

        Arguments:
            artifact: The artifact doing the storing
            path (str): The path to store
            name (str): If specified, the logical name that should map to `path`

        Returns:
            (list[ArtifactManifestEntry]): A list of manifest entries to store within the artifact
        """
        client_id = util.host_from_path(path)
        target_path = util.uri_from_path(path)
        target_artifact = self._cache.get_client_artifact(client_id)
        if not isinstance(target_artifact, wandb.Artifact):
            raise RuntimeError("Local Artifact not found - invalid reference")
        target_entry = target_artifact._manifest.entries[target_path]
        if target_entry is None:
            raise RuntimeError("Local entry not found - invalid reference")

        # Return the new entry
        return [
            ArtifactManifestEntry(
                path=name or os.path.basename(path),
                ref=path,
                size=0,
                digest=target_entry.digest,
            )
        ]
