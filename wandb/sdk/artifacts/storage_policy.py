"""Storage policy."""

from __future__ import annotations

import concurrent.futures
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.paths import FilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
    from wandb.sdk.internal.progress import ProgressFn


_POLICY_REGISTRY: dict[str, type[StoragePolicy]] = {}


class StoragePolicy(ABC):
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _POLICY_REGISTRY[cls.name()] = cls

    @classmethod
    def lookup_by_name(cls, name: str) -> type[StoragePolicy]:
        if policy := _POLICY_REGISTRY.get(name):
            return policy
        raise ValueError(f"Failed to find storage policy {name!r}")

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_config(
        cls, config: dict[str, Any], api: InternalApi | None = None
    ) -> StoragePolicy:
        raise NotImplementedError

    @abstractmethod
    def config(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def load_file(
        self,
        artifact: Artifact,
        manifest_entry: ArtifactManifestEntry,
        dest_path: str | None = None,
        executor: concurrent.futures.Executor | None = None,
    ) -> FilePathStr:
        raise NotImplementedError

    @abstractmethod
    def store_file(
        self,
        artifact_id: str,
        artifact_manifest_id: str,
        entry: ArtifactManifestEntry,
        preparer: StepPrepare,
        progress_callback: ProgressFn | None = None,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def store_reference(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: str | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> list[ArtifactManifestEntry]:
        raise NotImplementedError

    @abstractmethod
    def load_reference(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
        dest_path: str | None = None,
    ) -> FilePathStr | URIStr:
        raise NotImplementedError
