"""Artifact manifest v1."""

# Older-style type annotations required for Pydantic v1 / python 3.8 compatibility.
# ruff: noqa: UP006

from __future__ import annotations

from operator import itemgetter
from typing import Any, ClassVar, Dict, Literal, final

from pydantic import Field
from typing_extensions import Annotated

from wandb.sdk.lib.hashutil import HexMD5, _md5

from .._factories import make_storage_policy
from .._models.manifest import ArtifactManifestV1Data
from ..artifact_manifest import ArtifactManifest
from ..artifact_manifest_entry import ArtifactManifestEntry
from ..storage_policy import StoragePolicy


@final
class ArtifactManifestV1(ArtifactManifest):
    manifest_version: Annotated[Literal[1], Field(repr=False)] = 1
    entries: Dict[str, ArtifactManifestEntry] = Field(default_factory=dict)

    storage_policy: StoragePolicy = Field(
        default_factory=make_storage_policy, exclude=True, repr=False
    )

    @classmethod
    def from_manifest_json(cls, manifest_json: dict[str, Any]) -> ArtifactManifestV1:
        data = ArtifactManifestV1Data(**manifest_json)

        policy_name = data.storage_policy
        policy_cfg = data.storage_policy_config
        policy = StoragePolicy.lookup_by_name(policy_name).from_config(policy_cfg)
        return cls(
            manifest_version=data.version, entries=data.contents, storage_policy=policy
        )

    def to_manifest_json(self) -> dict:
        """This is the JSON that's stored in wandb_manifest.json.

        If include_local is True we also include the local paths to files. This is
        used to represent an artifact that's waiting to be saved on the current
        system. We don't need to include the local paths in the artifact manifest
        contents.
        """
        omit_entry_fields = {"path", "local_path", "skip_cache"}
        return {
            "version": self.manifest_version,
            "storagePolicy": self.storage_policy.name(),
            "storagePolicyConfig": self.storage_policy.config(),
            "contents": {
                path: entry.model_dump(exclude=omit_entry_fields, exclude_defaults=True)
                for path, entry in self.entries.items()
            },
        }

    _DIGEST_HEADER: ClassVar[bytes] = b"wandb-artifact-manifest-v1\n"
    """Encoded prefix/header for the ArtifactManifest digest."""

    def digest(self) -> HexMD5:
        hasher = _md5(self._DIGEST_HEADER)
        # sort by key (path)
        for path, entry in sorted(self.entries.items(), key=itemgetter(0)):
            hasher.update(f"{path}:{entry.digest}\n".encode())
        return hasher.hexdigest()

    def size(self) -> int:
        return sum(entry.size for entry in self.entries.values() if entry.size)
