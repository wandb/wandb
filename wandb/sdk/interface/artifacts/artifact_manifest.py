from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Union

from wandb import util
from wandb.sdk.lib.hashutil import B64MD5, ETag, HexMD5
from wandb.util import FilePathStr, LogicalFilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.sdk import wandb_artifacts
    from wandb.sdk.interface.artifacts import Artifact


@dataclass
class ArtifactManifestEntry:
    path: LogicalFilePathStr
    digest: Union[B64MD5, URIStr, FilePathStr, ETag]
    ref: Optional[Union[FilePathStr, URIStr]] = None
    birth_artifact_id: Optional[str] = None
    size: Optional[int] = None
    extra: Dict = field(default_factory=dict)
    local_path: Optional[str] = None

    def __post_init__(self) -> None:
        self.path = util.to_forward_slash_path(self.path)
        self.extra = self.extra or {}
        if self.local_path and self.size is None:
            raise ValueError("size required when local_path specified")

    def parent_artifact(self) -> "Artifact":
        """Get the artifact to which this artifact entry belongs.

        Returns:
            (Artifact): The parent artifact
        """
        raise NotImplementedError

    def download(self, root: Optional[str] = None) -> FilePathStr:
        """Download this artifact entry to the specified root path.

        Arguments:
            root: (str, optional) The root path in which to download this
                artifact entry. Defaults to the artifact's root.

        Returns:
            (str): The path of the downloaded artifact entry.

        """
        raise NotImplementedError

    def ref_target(self) -> str:
        """Get the reference URL that is targeted by this artifact entry.

        Returns:
            (str): The reference URL of this artifact entry.

        Raises:
            ValueError: If this artifact entry was not a reference.
        """
        if self.ref is None:
            raise ValueError("Only reference entries support ref_target().")
        return self.ref

    def ref_url(self) -> str:
        """Get a URL to this artifact entry.

        These URLs can be referenced by another artifact.

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
    entries: Dict[str, "ArtifactManifestEntry"]

    @classmethod
    def from_manifest_json(cls, manifest_json: Dict) -> "ArtifactManifest":
        if "version" not in manifest_json:
            raise ValueError("Invalid manifest format. Must contain version field.")
        version = manifest_json["version"]
        for sub in cls.__subclasses__():
            if sub.version() == version:
                return sub.from_manifest_json(manifest_json)
        raise ValueError("Invalid manifest version.")

    @classmethod
    def version(cls) -> int:
        raise NotImplementedError

    def __init__(
        self,
        storage_policy: "wandb_artifacts.WandbStoragePolicy",
        entries: Optional[Mapping[str, ArtifactManifestEntry]] = None,
    ) -> None:
        self.storage_policy = storage_policy
        self.entries = dict(entries) if entries else {}

    def to_manifest_json(self) -> Dict:
        raise NotImplementedError

    def digest(self) -> HexMD5:
        raise NotImplementedError

    def add_entry(self, entry: ArtifactManifestEntry) -> None:
        if (
            entry.path in self.entries
            and entry.digest != self.entries[entry.path].digest
        ):
            raise ValueError("Cannot add the same path twice: %s" % entry.path)
        self.entries[entry.path] = entry

    def get_entry_by_path(self, path: str) -> Optional[ArtifactManifestEntry]:
        return self.entries.get(path)

    def get_entries_in_directory(self, directory: str) -> List[ArtifactManifestEntry]:
        return [
            self.entries[entry_key]
            for entry_key in self.entries
            if entry_key.startswith(
                directory + "/"
            )  # entries use forward slash even for windows
        ]
