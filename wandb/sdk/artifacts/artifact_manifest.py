"""Artifact manifest."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from wandb.sdk.lib.hashutil import HexMD5

from ._models.base_model import ArtifactsBase

if TYPE_CHECKING:
    from .artifact_manifest_entry import ArtifactManifestEntry
    from .storage_policy import StoragePolicy


class ArtifactManifest(ArtifactsBase, ABC):
    # Note: we can't name this "version" since it conflicts with the prior
    # `version()` classmethod.
    manifest_version: Annotated[Any, Field(repr=False)]
    entries: dict[str, ArtifactManifestEntry] = Field(default_factory=dict)

    storage_policy: Annotated[StoragePolicy, Field(exclude=True, repr=False)]

    @classmethod
    def version(cls) -> int:
        return cls.model_fields["manifest_version"].default

    @classmethod
    @abstractmethod
    def from_manifest_json(cls, manifest_json: dict[str, Any]) -> ArtifactManifest:
        if (version := manifest_json.get("version")) is None:
            raise ValueError("Invalid manifest format. Must contain version field.")

        for sub in cls.__subclasses__():
            if sub.version() == version:
                return sub.from_manifest_json(manifest_json)
        raise ValueError("Invalid manifest version.")

    def __len__(self) -> int:
        return len(self.entries)

    @abstractmethod
    def to_manifest_json(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def digest(self) -> HexMD5:
        raise NotImplementedError

    @abstractmethod
    def size(self) -> int:
        raise NotImplementedError

    def add_entry(self, entry: ArtifactManifestEntry, overwrite: bool = False) -> None:
        if (
            (not overwrite)
            and (old_entry := self.entries.get(entry.path))
            and (entry.digest != old_entry.digest)
        ):
            raise ValueError(f"Cannot add the same path twice: {entry.path!r}")
        self.entries[entry.path] = entry

    def remove_entry(self, entry: ArtifactManifestEntry) -> None:
        try:
            del self.entries[entry.path]
        except LookupError:
            raise FileNotFoundError(f"Cannot remove missing entry: {entry.path!r}")

    def get_entry_by_path(self, path: str) -> ArtifactManifestEntry | None:
        return self.entries.get(path)

    def get_entries_in_directory(self, directory: str) -> list[ArtifactManifestEntry]:
        # entry keys (paths) use forward slash even for windows
        dir_prefix = f"{directory}/"
        return [obj for key, obj in self.entries.items() if key.startswith(dir_prefix)]
