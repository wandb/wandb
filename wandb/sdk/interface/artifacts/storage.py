from typing import TYPE_CHECKING, Optional, Sequence, Union

from wandb import util

from .artifacts import Artifact, ArtifactEntry

if TYPE_CHECKING:
    # need this import for type annotations, but want to avoid circular dependency
    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk.internal import progress


class StorageLayout:
    V1 = "V1"
    V2 = "V2"


class StoragePolicy:
    @classmethod
    def lookup_by_name(cls, name):
        for sub in cls.__subclasses__():
            if sub.name() == name:
                return sub
        return None

    @classmethod
    def name(cls):
        pass

    @classmethod
    def from_config(cls, config):
        pass

    def config(self):
        pass

    def load_file(
        self, artifact: Artifact, name: str, manifest_entry: ArtifactEntry
    ) -> str:
        raise NotImplementedError

    def store_file(
        self,
        artifact_id: str,
        artifact_manifest_id: str,
        entry: ArtifactEntry,
        preparer: "StepPrepare",
        progress_callback: Optional["progress.ProgressFn"] = None,
    ) -> bool:
        raise NotImplementedError

    def store_reference(
        self, artifact, path, name=None, checksum=True, max_objects=None
    ):
        raise NotImplementedError

    def load_reference(
        self,
        artifact: Artifact,
        name: str,
        manifest_entry: ArtifactEntry,
        local: bool = False,
    ) -> str:
        raise NotImplementedError


class StorageHandler:
    @property
    def scheme(self) -> str:
        """
        :return: The scheme to which this handler applies.
        :rtype: str
        """
        pass

    def load_path(
        self,
        artifact: Artifact,
        manifest_entry: ArtifactEntry,
        local: bool = False,
    ) -> Union[util.URIStr, util.FilePathStr]:
        """
        Loads the file or directory within the specified artifact given its
        corresponding index entry.

        :param manifest_entry: The index entry to load
        :type manifest_entry: ArtifactManifestEntry
        :return: A path to the file represented by `index_entry`
        :rtype: str
        """
        pass

    def store_path(
        self, artifact, path, name=None, checksum=True, max_objects=None
    ) -> Sequence[ArtifactEntry]:
        """
        Stores the file or directory at the given path within the specified artifact.

        :param path: The path to store
        :type path: str
        :param name: If specified, the logical name that should map to `path`
        :type name: str
        :return: A list of manifest entries to store within the artifact
        :rtype: list(ArtifactManifestEntry)
        """
        pass
