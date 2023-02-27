from typing import TYPE_CHECKING, Dict, Optional, Sequence, Type, Union

from wandb.sdk.interface.artifacts import Artifact, ArtifactManifestEntry
from wandb.util import FilePathStr, URIStr

if TYPE_CHECKING:
    # need this import for type annotations, but want to avoid circular dependency
    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk.internal import progress


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
        self, artifact: Artifact, manifest_entry: ArtifactManifestEntry
    ) -> str:
        raise NotImplementedError

    def store_file(
        self,
        artifact_id: str,
        artifact_manifest_id: str,
        entry: ArtifactManifestEntry,
        preparer: "StepPrepare",
        progress_callback: Optional["progress.ProgressFn"] = None,
    ) -> bool:
        raise NotImplementedError

    def store_reference(
        self,
        artifact: Artifact,
        path: Union[URIStr, FilePathStr],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        raise NotImplementedError

    def load_reference(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> str:
        raise NotImplementedError


class StorageHandler:
    @property
    def scheme(self) -> str:
        """The scheme this handler applies to.

        :return: The scheme to which this handler applies.
        :rtype: str
        """
        raise NotImplementedError

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> Union[URIStr, FilePathStr]:
        """Load a file or directory given the corresponding index entry.

        :param manifest_entry: The index entry to load
        :type manifest_entry: ArtifactManifestEntry
        :return: A path to the file represented by `index_entry`
        :rtype: str
        """
        raise NotImplementedError

    def store_path(
        self,
        artifact: Artifact,
        path: Union[URIStr, FilePathStr],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        """Store the file or directory at the given path to the specified artifact.

        :param path: The path to store
        :type path: str
        :param name: If specified, the logical name that should map to `path`
        :type name: str
        :return: A list of manifest entries to store within the artifact
        :rtype: list(ArtifactManifestEntry)
        """
        raise NotImplementedError
