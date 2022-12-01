from typing import TYPE_CHECKING, List, Dict, Optional, Union

from wandb import hashutil, util


class ArtifactEntry:
    path: util.LogicalFilePathStr
    ref: Optional[Union[util.FilePathStr, util.URIStr]]
    digest: Union[hashutil.B64MD5, util.URIStr, util.FilePathStr, hashutil.ETag]
    birth_artifact_id: Optional[str]
    size: Optional[int]
    extra: Dict
    local_path: Optional[str]

    def parent_artifact(self) -> "Artifact":
        """
        Get the artifact to which this artifact entry belongs.

        Returns:
            (Artifact): The parent artifact
        """
        raise NotImplementedError

    def download(self, root: Optional[str] = None) -> util.FilePathStr:
        """
        Downloads this artifact entry to the specified root path.

        Arguments:
            root: (str, optional) The root path in which to download this
                artifact entry. Defaults to the artifact's root.

        Returns:
            (str): The path of the downloaded artifact entry.

        """
        raise NotImplementedError

    def ref_target(self) -> str:
        """
        Gets the reference URL that this artifact entry targets.
        Returns:
            (str): The reference URL of this artifact entry.
        Raises:
            ValueError: If this artifact entry was not a reference.
        """
        raise NotImplementedError

    def ref_url(self) -> str:
        """
        Gets a URL to this artifact entry such that it can be referenced
        by another artifact.

        Returns:
            (str): A URL representing this artifact entry.

        Examples:
            Basic usage
            ```
            ref_url = source_artifact.get_path('file.txt').ref_url()
            derived_artifact.add_reference(ref_url)
            ```
        """
        raise NotImplementedError


class ArtifactManifest:
    entries: Dict[str, ArtifactEntry]

    @classmethod
    # TODO: we don't need artifact here.
    def from_manifest_json(cls, artifact, manifest_json) -> "ArtifactManifest":
        if "version" not in manifest_json:
            raise ValueError("Invalid manifest format. Must contain version field.")
        version = manifest_json["version"]
        for sub in cls.__subclasses__():
            if sub.version() == version:
                return sub.from_manifest_json(artifact, manifest_json)
        raise ValueError("Invalid manifest version.")

    @classmethod
    def version(cls) -> int:
        raise NotImplementedError()

    def __init__(
        self,
        artifact,
        storage_policy: "StoragePolicy",
        entries=None,
    ) -> None:
        self.artifact = artifact
        self.storage_policy = storage_policy
        self.entries = entries or {}

    def to_manifest_json(self) -> Dict:
        raise NotImplementedError()

    def digest(self) -> hashutil.HexMD5:
        raise NotImplementedError()

    def add_entry(self, entry) -> None:
        if (
            entry.path in self.entries
            and entry.digest != self.entries[entry.path].digest
        ):
            raise ValueError("Cannot add the same path twice: %s" % entry.path)
        self.entries[entry.path] = entry

    def get_entry_by_path(self, path: str) -> Optional[ArtifactEntry]:
        return self.entries.get(path)

    def get_entries_in_directory(self, directory) -> List[ArtifactEntry]:
        return [
            self.entries[entry_key]
            for entry_key in self.entries
            if entry_key.startswith(
                directory + "/"
            )  # entries use forward slash even for windows
        ]
