"""WB artifact storage handler."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from wandb._strutils import removeprefix
from wandb.apis import PublicApi
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import StorageHandler
from wandb.sdk.lib.hashutil import b64_to_hex_id, hex_to_b64_id
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    from urllib.parse import ParseResult

    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


class WBArtifactHandler(StorageHandler):
    """Handles loading and storing Artifact reference-type files."""

    _scheme: Literal["wandb-artifact"]
    _cache: ArtifactFileCache
    _client: PublicApi | None

    def __init__(self) -> None:
        self._scheme = "wandb-artifact"
        self._cache = get_artifact_file_cache()
        self._client = None

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

    @property
    def client(self) -> PublicApi:
        if self._client is None:
            self._client = PublicApi()
        return self._client

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        """Load the file in the specified artifact given its corresponding entry.

        Download the referenced artifact; create and return a new symlink to the caller.

        Args:
            manifest_entry (ArtifactManifestEntry): The index entry to load

        Returns:
            (os.PathLike): A path to the file represented by `index_entry`
        """
        from wandb.sdk.artifacts.artifact import Artifact  # avoids circular import

        # We don't check for cache hits here. Since we have 0 for size (since this
        # is a cross-artifact reference which and we've made the choice to store 0
        # in the size field), we can't confirm if the file is complete. So we just
        # rely on the dep_artifact entry's download() method to do its own cache
        # check.

        # Parse the reference path and download the artifact if needed
        parsed = urlparse(manifest_entry.ref)
        artifact_id = hex_to_b64_id(parsed.netloc)
        artifact_file_path = removeprefix(str(parsed.path), "/")

        dep_artifact = Artifact._from_id(artifact_id, self.client.client)
        assert dep_artifact is not None
        link_target_path: URIStr | FilePathStr
        if local:
            link_target_path = dep_artifact.get_entry(artifact_file_path).download()
        else:
            link_target_path = dep_artifact.get_entry(artifact_file_path).ref_target()
        return link_target_path

    def store_path(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: StrPath | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> list[ArtifactManifestEntry]:
        """Store the file or directory at the given path into the specified artifact.

        Recursively resolves the reference until the result is a concrete asset.

        Args:
            artifact: The artifact doing the storing path (str): The path to store name
            (str): If specified, the logical name that should map to `path`

        Returns:
            (list[ArtifactManifestEntry]): A list of manifest entries to store within
            the artifact
        """
        from wandb.sdk.artifacts.artifact import Artifact  # avoids circular import

        # Recursively resolve the reference until a concrete asset is found
        # TODO: Consider resolving server-side for performance improvements.
        curr_path: URIStr | FilePathStr | None = path
        while curr_path and (parsed := urlparse(curr_path)).scheme == self._scheme:
            artifact_id = hex_to_b64_id(parsed.netloc)
            artifact_file_path = removeprefix(parsed.path, "/")

            target_artifact = Artifact._from_id(artifact_id, self.client.client)
            assert target_artifact is not None

            entry = target_artifact.manifest.get_entry_by_path(artifact_file_path)
            assert entry is not None
            curr_path = entry.ref

        # Create the path reference
        assert target_artifact is not None
        assert target_artifact.id is not None
        path = (
            f"{self._scheme}://{b64_to_hex_id(target_artifact.id)}/{artifact_file_path}"
        )

        # Return the new entry
        assert entry is not None
        return [
            ArtifactManifestEntry(
                path=name or os.path.basename(path),
                ref=path,
                size=0,
                digest=entry.digest,
            )
        ]
