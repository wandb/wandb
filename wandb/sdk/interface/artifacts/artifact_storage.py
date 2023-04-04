from typing import TYPE_CHECKING, Dict, Optional, Sequence, Type, Union

from wandb.util import FilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk.interface.artifacts import Artifact, ArtifactManifestEntry
    from wandb.sdk.internal.progress import ProgressFn


class StorageLayout:
    V1 = "V1"
    V2 = "V2"


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
        self, artifact: "Artifact", manifest_entry: "ArtifactManifestEntry"
    ) -> str:
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
        artifact: "Artifact",
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
    ) -> str:
        raise NotImplementedError


class StorageHandler:
    @property
    def scheme(self) -> str:
        """The scheme this handler applies to.

        Returns:
            The scheme to which this handler applies.
        """
        raise NotImplementedError

    def load_path(
        self,
        manifest_entry: "ArtifactManifestEntry",
        local: bool = False,
    ) -> Union[URIStr, FilePathStr]:
        """Load a file or directory given the corresponding index entry.

        Args:
            manifest_entry: The index entry to load
            local: Whether to load the file locally or not

        Returns:
            A path to the file represented by `index_entry`
        """
        raise NotImplementedError

    def store_path(
        self,
        artifact: "Artifact",
        path: Union[URIStr, FilePathStr],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence["ArtifactManifestEntry"]:
        """Store the file or directory at the given path to the specified artifact.

        Args:
            path: The path to store
            name: If specified, the logical name that should map to `path`
            checksum: Whether to compute the checksum of the file
            max_objects: The maximum number of objects to store

        Returns:
            A list of manifest entries to store within the artifact
        """
        raise NotImplementedError
