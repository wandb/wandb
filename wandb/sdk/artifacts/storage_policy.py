"""Storage policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.paths import FilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
    from wandb.sdk.internal.progress import ProgressFn


class StoragePolicy:
    @classmethod
    def lookup_by_name(cls, name: str) -> type[StoragePolicy]:
        import wandb.sdk.artifacts.storage_policies  # noqa: F401

        for sub in cls.__subclasses__():
            if sub.name() == name:
                return sub
        raise NotImplementedError(f"Failed to find storage policy '{name}'")

    @classmethod
    def name(cls) -> str:
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: dict, api: InternalApi | None = None) -> StoragePolicy:
        raise NotImplementedError

    def config(self) -> dict:
        raise NotImplementedError

    def load_file(
        self,
        artifact: Artifact,
        manifest_entry: ArtifactManifestEntry,
        dest_path: str | None = None,
    ) -> FilePathStr:
        raise NotImplementedError

    def store_file(
        self,
        artifact_id: str,
        artifact_manifest_id: str,
        entry: ArtifactManifestEntry,
        preparer: StepPrepare,
        progress_callback: ProgressFn | None = None,
    ) -> bool:
        raise NotImplementedError

    def store_reference(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: str | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> Sequence[ArtifactManifestEntry]:
        raise NotImplementedError

    def load_reference(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
        dest_path: str | None = None,
    ) -> FilePathStr | URIStr:
        raise NotImplementedError
