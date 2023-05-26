"""Artifact manifest v1."""
from typing import Any, Dict, Mapping, Optional

from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_policies.wandb_storage_policy import WandbStoragePolicy
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.lib.hashutil import HexMD5, _md5


class ArtifactManifestV1(ArtifactManifest):
    @classmethod
    def version(cls) -> int:
        return 1

    @classmethod
    def from_manifest_json(cls, manifest_json: Dict) -> "ArtifactManifestV1":
        if manifest_json["version"] != cls.version():
            raise ValueError(
                "Expected manifest version 1, got %s" % manifest_json["version"]
            )

        storage_policy_name = manifest_json["storagePolicy"]
        storage_policy_config = manifest_json.get("storagePolicyConfig", {})
        storage_policy_cls = StoragePolicy.lookup_by_name(storage_policy_name)
        if storage_policy_cls is None:
            raise ValueError('Failed to find storage policy "%s"' % storage_policy_name)
        if not issubclass(storage_policy_cls, WandbStoragePolicy):
            raise ValueError(
                "No handler found for storage handler of type '%s'"
                % storage_policy_name
            )

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
            )
            for name, val in manifest_json["contents"].items()
        }

        return cls(storage_policy_cls.from_config(storage_policy_config), entries)

    def __init__(
        self,
        storage_policy: "WandbStoragePolicy",
        entries: Optional[Mapping[str, ArtifactManifestEntry]] = None,
    ) -> None:
        super().__init__(storage_policy, entries=entries)

    def to_manifest_json(self) -> Dict:
        """This is the JSON that's stored in wandb_manifest.json.

        If include_local is True we also include the local paths to files. This is
        used to represent an artifact that's waiting to be saved on the current
        system. We don't need to include the local paths in the artifact manifest
        contents.
        """
        contents = {}
        for entry in sorted(self.entries.values(), key=lambda k: k.path):
            json_entry: Dict[str, Any] = {
                "digest": entry.digest,
            }
            if entry.birth_artifact_id:
                json_entry["birthArtifactID"] = entry.birth_artifact_id
            if entry.ref:
                json_entry["ref"] = entry.ref
            if entry.extra:
                json_entry["extra"] = entry.extra
            if entry.size is not None:
                json_entry["size"] = entry.size
            contents[entry.path] = json_entry
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
