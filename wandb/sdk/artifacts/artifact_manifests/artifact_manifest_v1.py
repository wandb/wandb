"""Artifact manifest v1."""

from __future__ import annotations

from operator import attrgetter
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.hashutil import HexMD5, _md5


class _ValidatedManifestV1(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
    )

    version: Literal[1]
    storage_policy: str  #: Name of the storage policy.
    storage_policy_config: dict[str, Any] = Field(default_factory=dict)
    contents: dict[str, dict[str, Any]]


class ArtifactManifestV1(ArtifactManifest):
    @classmethod
    def version(cls) -> int:
        return 1

    @classmethod
    def from_manifest_json(
        cls, manifest_json: dict, api: InternalApi | None = None
    ) -> ArtifactManifestV1:
        # if (version := manifest_json["version"]) != cls.version():
        #     raise ValueError(
        #         f"Expected manifest version {cls.version()!r}, got {version!r}"
        #     )

        # storage_policy_name = manifest_json["storagePolicy"]
        # storage_policy_config = manifest_json.get("storagePolicyConfig", {})
        # storage_policy_cls = StoragePolicy.lookup_by_name(storage_policy_name)

        v = _ValidatedManifestV1.model_validate(manifest_json)

        # entries: Mapping[str, ArtifactManifestEntry]

        entries = {
            # name: ArtifactManifestEntry(
            #     path=name,
            #     digest=val["digest"],
            #     birth_artifact_id=val.get("birthArtifactID"),
            #     ref=val.get("ref"),
            #     size=val.get("size"),
            #     extra=val.get("extra"),
            #     local_path=val.get("local_path"),
            #     skip_cache=val.get("skip_cache"),
            # )
            # for name, val in manifest_json["contents"].items()
            name: ArtifactManifestEntry(path=name, **entry_dict)
            for name, entry_dict in v.contents.items()
        }

        return cls(
            StoragePolicy.lookup_by_name(v.storage_policy).from_config(
                v.storage_policy_config, api=api
            ),
            entries,
        )

    def __init__(
        self,
        storage_policy: StoragePolicy,
        entries: Mapping[str, ArtifactManifestEntry] | None = None,
    ) -> None:
        super().__init__(storage_policy, entries=entries)

    def to_manifest_json(self) -> dict:
        """This is the JSON that's stored in wandb_manifest.json.

        If include_local is True we also include the local paths to files. This is
        used to represent an artifact that's waiting to be saved on the current
        system. We don't need to include the local paths in the artifact manifest
        contents.
        """
        # contents = {}
        # for entry in sorted(self.entries.values(), key=lambda k: k.path):
        #     json_entry: dict[str, Any] = {
        #         "digest": entry.digest,
        #     }
        #     if entry.birth_artifact_id:
        #         json_entry["birthArtifactID"] = entry.birth_artifact_id
        #     if entry.ref:
        #         json_entry["ref"] = entry.ref
        #     if entry.extra:
        #         json_entry["extra"] = entry.extra
        #     if entry.size is not None:
        #         json_entry["size"] = entry.size
        #     contents[entry.path] = json_entry

        contents = {
            entry.path: entry.model_dump(
                exclude={"path", "local_path", "skip_cache"},
                exclude_defaults=True,
                exclude_none=True,
                by_alias=True,
            )
            for entry in sorted(self.entries.values(), key=attrgetter("path"))
        }
        return {
            "version": self.version(),
            "storagePolicy": self.storage_policy.name(),
            "storagePolicyConfig": self.storage_policy.config() or {},
            "contents": contents,
        }

    def digest(self) -> HexMD5:
        hasher = _md5()
        hasher.update(b"wandb-artifact-manifest-v1\n")
        for name, entry in sorted(self.entries.items(), key=lambda kv: kv[0]):
            hasher.update(f"{name}:{entry.digest}\n".encode())
        return HexMD5(hasher.hexdigest())
