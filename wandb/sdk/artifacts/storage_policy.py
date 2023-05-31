"""Storage policy."""
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Type, Union

from wandb.sdk.lib.paths import FilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk.artifacts.artifact import Artifact as ArtifactInterface
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
    from wandb.sdk.internal.progress import ProgressFn


class StoragePolicy:
    @classmethod
    def lookup_by_name(cls, name: str) -> Optional[Type["StoragePolicy"]]:
        for sub in cls.__subclasses__():
            if sub.name() == name:
                return sub
        return None

    @classmethod
    def name(cls) -> str:
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: Dict) -> "StoragePolicy":
        raise NotImplementedError

    def config(self) -> Dict:
        raise NotImplementedError

    def load_file(
        self, artifact: "ArtifactInterface", manifest_entry: "ArtifactManifestEntry"
    ) -> FilePathStr:
        raise NotImplementedError

    def store_file_sync(
        self,
        artifact_id: str,
        artifact_manifest_id: str,
        entry: "ArtifactManifestEntry",
        preparer: "StepPrepare",
        progress_callback: Optional["ProgressFn"] = None,
    ) -> bool:
        raise NotImplementedError

    async def store_file_async(
        self,
        artifact_id: str,
        artifact_manifest_id: str,
        entry: "ArtifactManifestEntry",
        preparer: "StepPrepare",
        progress_callback: Optional["ProgressFn"] = None,
    ) -> bool:
        """Async equivalent to `store_file_sync`."""
        raise NotImplementedError

    def store_reference(
        self,
        artifact: "ArtifactInterface",
        path: Union[URIStr, FilePathStr],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence["ArtifactManifestEntry"]:
        raise NotImplementedError

    def load_reference(
        self,
        manifest_entry: "ArtifactManifestEntry",
        local: bool = False,
    ) -> Union[FilePathStr, URIStr]:
        raise NotImplementedError
