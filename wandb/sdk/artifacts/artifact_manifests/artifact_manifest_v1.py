"""Artifact manifest v1."""

# Older-style type annotations required for Pydantic v1 / python 3.8 compatibility.
# ruff: noqa: UP006

from __future__ import annotations

from operator import itemgetter
from typing import Annotated, Any, Dict, Final, Literal, final

from pydantic import ConfigDict, Field

from wandb._pydantic import field_validator, to_camel
from wandb.sdk.artifacts._base_model import ArtifactsBase
from wandb.sdk.artifacts._factories import make_storage_policy
from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.hashutil import HexMD5, _md5


class _ManifestV1Data(ArtifactsBase):
    model_config = ConfigDict(frozen=True, alias_generator=to_camel)

    version: Literal[1]
    entries: Dict[str, ArtifactManifestEntry] = Field(alias="contents")

    storage_policy: str
    storage_policy_config: Annotated[Dict[str, Any], Field(alias="storagePolicyConfig")]

    @field_validator("entries", mode="before")
    def _validate_entries(cls, v: Any) -> dict[str, ArtifactManifestEntry]:
        # The dict keys should be `ArtifactManifestEntry.path`, but they're
        # not part of the serialized JSON object.  We add it back in validation.
        # Note that the key deliberately overrides the existing "path" value
        # if by chance it **was** serialized in the dict.
        return {
            key: ArtifactManifestEntry(**{**dict(obj), "path": key})
            for key, obj in v.items()
        }


#: Inner ArtifactManifestEntry fields to keep when dumping the ArtifactManifest to JSON.
_JSON_ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    {"digest", "birth_artifact_id", "ref", "extra", "size"}
)


@final
class ArtifactManifestV1(ArtifactManifest):
    v: Literal[1] = 1
    entries: Dict[str, ArtifactManifestEntry] = Field(default_factory=dict)

    storage_policy: StoragePolicy = Field(
        default_factory=make_storage_policy, exclude=True, repr=False
    )

    @classmethod
    def from_manifest_json(
        cls, manifest_json: dict[str, Any], api: InternalApi | None = None
    ) -> ArtifactManifestV1:
        data = _ManifestV1Data(**manifest_json)
        policy_cls = StoragePolicy.lookup_by_name(data.storage_policy)
        return cls(
            v=data.version,
            entries=data.entries,
            storage_policy=policy_cls.from_config(data.storage_policy_config, api=api),
        )

    def to_manifest_json(self) -> dict:
        """This is the JSON that's stored in wandb_manifest.json.

        If include_local is True we also include the local paths to files. This is
        used to represent an artifact that's waiting to be saved on the current
        system. We don't need to include the local paths in the artifact manifest
        contents.
        """
        kept_fields = set(_JSON_ENTRY_FIELDS)
        return {
            "version": self.version(),
            "storagePolicy": self.storage_policy.name(),
            "storagePolicyConfig": self.storage_policy.config(),
            "contents": {
                key: obj.model_dump(include=kept_fields, exclude_defaults=True)
                for key, obj in self.entries.items()
            },
        }

    def digest(self) -> HexMD5:
        hasher = _md5()
        hasher.update(b"wandb-artifact-manifest-v1\n")
        # sort by key (path)
        for name, entry in sorted(self.entries.items(), key=itemgetter(0)):
            hasher.update(f"{name}:{entry.digest}\n".encode())
        return HexMD5(hasher.hexdigest())
