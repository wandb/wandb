"""Artifact manifest v1."""

# Older-style type annotations required for Pydantic v1 / python 3.8 compatibility.

from __future__ import annotations

from operator import itemgetter
from typing import final

from wandb.sdk.lib.hashutil import HexMD5, _md5

from ..artifact_manifest import ArtifactManifest

# class V1ManifestData(ArtifactsBase, frozen=True, alias_generator=to_camel):
#     """Data model for the v1 artifact manifest."""

#     version: Literal[1]
#     contents: Dict[str, Dict[str, Any]]
#     storage_policy: str
#     storage_policy_config: Dict[str, Any]


@final
class ArtifactManifestV1(ArtifactManifest):
    # manifest_version: Annotated[Literal[1], Field(alias="version", repr=False)] = 1
    # entries: Dict[str, ArtifactManifestEntry] = Field(
    #     default_factory=dict, alias="contents"
    # )

    # storage_policy: StoragePolicy = Field(
    #     default_factory=make_storage_policy, exclude=True, repr=False
    # )

    # @field_validator("entries", mode="before")
    # def _validate_entries(cls, v: Any) -> Any:
    #     # The dict keys should be the `entry.path` values, but they've
    #     # historically been dropped from the JSON objects. This restores
    #     # them on instantiation.
    #     # Pydantic will handle converting dicts -> ArtifactManifestEntries.
    #     return {path: {**dict(entry), "path": path} for path, entry in v.items()}

    # @classmethod
    # def from_manifest_json(
    #     cls, manifest_json: dict[str, Any], api: InternalApi | None = None
    # ) -> ArtifactManifestV1:
    #     data = V1ManifestData(**manifest_json)

    #     policy_name = data.storage_policy
    #     policy_cfg = data.storage_policy_config
    #     policy = StoragePolicy.lookup_by_name(policy_name).from_config(policy_cfg, api)
    #     return cls(
    #         manifest_version=data.version, entries=data.contents, storage_policy=policy
    #     )

    def to_manifest_json(self) -> dict:
        """This is the JSON that's stored in wandb_manifest.json.

        If include_local is True we also include the local paths to files. This is
        used to represent an artifact that's waiting to be saved on the current
        system. We don't need to include the local paths in the artifact manifest
        contents.
        """
        omit_entry_fields = {"path", "local_path", "skip_cache"}
        return {
            # "version": self.manifest_version,
            "version": self.data.version,
            "storagePolicy": self.storage_policy.name(),
            "storagePolicyConfig": self.storage_policy.config(),
            "contents": {
                path: entry.model_dump(exclude=omit_entry_fields, exclude_defaults=True)
                for path, entry in self.entries.items()
            },
        }

    def digest(self) -> HexMD5:
        hasher = _md5()
        hasher.update(b"wandb-artifact-manifest-v1\n")
        # sort by key (path)
        for name, entry in sorted(self.entries.items(), key=itemgetter(0)):
            hasher.update(f"{name}:{entry.digest}\n".encode())
        return HexMD5(hasher.hexdigest())
