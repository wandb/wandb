"""Artifact manifest entry."""
import os
from typing import TYPE_CHECKING

import wandb
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.hashutil import b64_to_hex_id, md5_file_b64

if TYPE_CHECKING:
    from wandb.sdk.artifacts.public_artifact import Artifact as PublicArtifact


class DownloadedArtifactEntry(ArtifactManifestEntry):
    def __init__(
        self,
        entry: "ArtifactManifestEntry",
        parent_artifact: "PublicArtifact",
    ):
        super().__init__(
            path=entry.path,
            digest=entry.digest,
            ref=entry.ref,
            birth_artifact_id=entry.birth_artifact_id,
            size=entry.size,
            extra=entry.extra,
            local_path=entry.local_path,
        )
        self._parent_artifact = parent_artifact

    @property
    def name(self):
        # TODO(hugh): add telemetry to see if anyone is still using this.
        wandb.termwarn("ArtifactManifestEntry.name is deprecated, use .path instead")
        return self.path

    def parent_artifact(self):
        return self._parent_artifact

    def copy(self, cache_path, target_path):
        raise NotImplementedError()

    def download(self, root=None):
        root = root or self._parent_artifact._default_root()
        dest_path = os.path.join(root, self.path)

        self._parent_artifact._add_download_root(root)
        manifest = self._parent_artifact._load_manifest()

        # Skip checking the cache (and possibly downloading) if the file already exists
        # and has the digest we're expecting.
        entry = manifest.entries[self.path]
        if os.path.exists(dest_path) and entry.digest == md5_file_b64(dest_path):
            return dest_path

        if self.ref is not None:
            cache_path = manifest.storage_policy.load_reference(entry, local=True)
        else:
            cache_path = manifest.storage_policy.load_file(self._parent_artifact, entry)

        return filesystem.copy_or_overwrite_changed(cache_path, dest_path)

    def ref_target(self):
        manifest = self._parent_artifact._load_manifest()
        if self.ref is not None:
            return manifest.storage_policy.load_reference(
                manifest.entries[self.path],
                local=False,
            )
        raise ValueError("Only reference entries support ref_target().")

    def ref_url(self):
        return (
            "wandb-artifact://"
            + b64_to_hex_id(self._parent_artifact.id)
            + "/"
            + self.path
        )
