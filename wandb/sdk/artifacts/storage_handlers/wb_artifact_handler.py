"""WB artifact storage handler."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from wandb.apis.public import Api
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import StorageHandler
from wandb.sdk.lib.hashutil import b64_to_hex_id, hex_to_b64_id
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    from urllib.parse import ParseResult

    from wandb.sdk.artifacts.artifact import Artifact


class WBArtifactHandler(StorageHandler):
    """Handles loading and storing Artifact reference-type files."""

    _scheme: Literal["wandb-artifact"]
    _client: Api | None

    def __init__(self) -> None:
        self._scheme = "wandb-artifact"
        self._client = None

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

    @property
    def client(self) -> Api:
        if self._client is None:
            self._client = Api()
        return self._client

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
        dest_path: StrPath | None = None,
    ) -> URIStr | FilePathStr:
        """Load the file in the referenced artifact given its corresponding entry.

        Args:
            manifest_entry (ArtifactManifestEntry): The index entry to load
            local: Whether to download the referenced file or just resolve its target
            dest_path: If set, download the referenced file to this path instead of
                the referenced artifact's download root, bypassing the cache

        Returns:
            The local path of the referenced file, or its reference target when
            `local` is False.
        """
        # We don't check for cache hits here. Cross-artifact references store 0
        # in the size field, so we can't confirm if a file is complete. Without a
        # dest_path we rely on the referenced entry's download() to do its own
        # check; with one, the caller has already rejected the file at dest_path.

        # Parse the reference path and download the artifact if needed
        parsed = urlparse(manifest_entry.ref)
        artifact_id = hex_to_b64_id(parsed.netloc)
        artifact_file_path = str(parsed.path).removeprefix("/")

        dep_artifact = self.client._artifact_from_id(artifact_id)
        assert dep_artifact is not None
        dep_entry = dep_artifact.get_entry(artifact_file_path)
        if not local:
            return dep_entry.ref_target()
        if dest_path is None:
            return dep_entry.download()

        # Skipping the cache: write the referenced file straight into dest_path
        # through the dependency's storage policy. Staging it in the dependency's
        # download root would share a path between same-named artifacts from
        # different projects, and the policy's writer replaces dest_path
        # atomically like any other skip-cache download.
        policy = dep_artifact.manifest.storage_policy
        if dep_entry.ref is not None:
            return policy.load_reference(
                dep_entry, local=True, dest_path=str(dest_path)
            )
        return policy.load_file(dep_artifact, dep_entry, dest_path=str(dest_path))

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
        # Recursively resolve the reference until a concrete asset is found
        # TODO: Consider resolving server-side for performance improvements.
        curr_path: URIStr | FilePathStr | None = path

        while curr_path and (parsed := urlparse(curr_path)).scheme == self._scheme:
            artifact_id = hex_to_b64_id(parsed.netloc)
            artifact_file_path = parsed.path.removeprefix("/")

            target_artifact = self.client._artifact_from_id(artifact_id)
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
