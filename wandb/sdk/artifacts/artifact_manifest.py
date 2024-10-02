"""Artifact manifest."""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.hashutil import HexMD5

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
    from wandb.sdk.artifacts.storage_policy import StoragePolicy


class ArtifactManifest:
    entries: dict[str, ArtifactManifestEntry]

    @classmethod
    def from_manifest_json(
        cls, manifest_json: dict, api: InternalApi | None = None
    ) -> ArtifactManifest:
        if "version" not in manifest_json:
            raise ValueError("Invalid manifest format. Must contain version field.")
        version = manifest_json["version"]
        for sub in cls.__subclasses__():
            if sub.version() == version:
                return sub.from_manifest_json(manifest_json, api=api)
        raise ValueError("Invalid manifest version.")

    @classmethod
    def version(cls) -> int:
        raise NotImplementedError

    def __init__(
        self,
        storage_policy: StoragePolicy,
        entries: Mapping[str, ArtifactManifestEntry] | None = None,
    ) -> None:
        self.storage_policy = storage_policy
        self.entries = dict(entries) if entries else {}

    def __len__(self) -> int:
        return len(self.entries)

    def to_manifest_json(self) -> dict:
        raise NotImplementedError

    def digest(self) -> HexMD5:
        raise NotImplementedError

    def add_entry(self, entry: ArtifactManifestEntry) -> None:
        if (
            entry.path in self.entries
            and entry.digest != self.entries[entry.path].digest
        ):
            raise ValueError("Cannot add the same path twice: {}".format(entry.path))
        self.entries[entry.path] = entry

    def remove_entry(self, entry: ArtifactManifestEntry) -> None:
        if entry.path not in self.entries:
            raise FileNotFoundError(f"Cannot remove missing entry: '{entry.path}'")
        del self.entries[entry.path]

    def get_entry_by_path(self, path: str) -> ArtifactManifestEntry | None:
        return self.entries.get(path)

    def get_entries_in_directory(self, directory: str) -> list[ArtifactManifestEntry]:
        return [
            self.entries[entry_key]
            for entry_key in self.entries
            if entry_key.startswith(
                directory + "/"
            )  # entries use forward slash even for windows
        ]
