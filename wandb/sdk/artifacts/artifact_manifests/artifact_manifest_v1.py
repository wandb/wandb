"""Artifact manifest v1."""

from typing import Any, Dict, Mapping, Optional

from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.hashutil import HexMD5, _md5


class ArtifactManifestV1(ArtifactManifest):
    @classmethod
    def version(cls) -> int:
        return 1

    @classmethod
    def from_manifest_json(
        cls, manifest_json: Dict, api: Optional[InternalApi] = None
    ) -> "ArtifactManifestV1":
        if manifest_json["version"] != cls.version():
            raise ValueError(
                "Expected manifest version 1, got {}".format(manifest_json["version"])
            )

        storage_policy_name = manifest_json["storagePolicy"]
        storage_policy_config = manifest_json.get("storagePolicyConfig", {})
        storage_policy_cls = StoragePolicy.lookup_by_name(storage_policy_name)

        entries: Mapping[str, ArtifactManifestEntry]
        entries = {
            name: ArtifactManifestEntry(
                path=name,
                digest=val["digest"],
                birth_artifact_id=val.get("birthArtifactID"),
                ref=val.get("ref"),
                size=val.get("size"),
                extra=val.get("extra"),
                local_path=val.get("local_path"),
                skip_cache=val.get("skip_cache"),
            )
            for name, val in manifest_json["contents"].items()
        }

        return cls(
            storage_policy_cls.from_config(storage_policy_config, api=api), entries
        )

    def __init__(
        self,
        storage_policy: "StoragePolicy",
        entries: Optional[Mapping[str, ArtifactManifestEntry]] = None,
    ) -> None:
        super().__init__(storage_policy, entries=entries)

    def to_manifest_json(self) -> Dict:
        """This is the JSON that's stored in wandb_manifest.json."""
        contents = {}
        for entry in sorted(self.entries.values(), key=lambda k: k.path):
            entry_json = entry.to_json()
            path = entry_json.pop("path")
            contents[path] = entry_json
        return {
            "version": self.__class__.version(),
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
