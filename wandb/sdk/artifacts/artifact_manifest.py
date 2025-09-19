"""Artifact manifest."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict

from pydantic import Field
from typing_extensions import Annotated

from wandb.sdk.artifacts._base_model import ArtifactsBase
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.hashutil import HexMD5

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
    from wandb.sdk.artifacts.storage_policy import StoragePolicy


class ArtifactManifest(ArtifactsBase, ABC):
    # Note: this can't be named "version" since it conflicts with the prior `version()` classmethod.
    manifest_version: Annotated[int, Field(alias="version", repr=False)]
    entries: Dict[str, ArtifactManifestEntry] = Field(default_factory=dict)  # noqa: UP006

    storage_policy: StoragePolicy = Field(exclude=True, repr=False)

    @classmethod
    def version(cls) -> int:
        return cls.model_fields["manifest_version"].default

    @classmethod
    @abstractmethod
    def from_manifest_json(
        cls, manifest_json: dict[str, Any], api: InternalApi | None = None
    ) -> ArtifactManifest:
        if (version := manifest_json.get("version")) is None:
            raise ValueError("Invalid manifest format. Must contain version field.")

        for sub in cls.__subclasses__():
            if sub.version() == version:
                return sub.from_manifest_json(manifest_json, api=api)
        raise ValueError("Invalid manifest version.")

    def __len__(self) -> int:
        return len(self.entries)

    @abstractmethod
    def to_manifest_json(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def digest(self) -> HexMD5:
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
