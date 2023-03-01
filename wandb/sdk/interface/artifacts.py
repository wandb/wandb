import contextlib
import hashlib
import os
import random
import tempfile
from dataclasses import dataclass, field
from typing import (
    IO,
    TYPE_CHECKING,
    ContextManager,
    Dict,
    Generator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)

import wandb
from wandb import env, util
from wandb.data_types import WBValue
from wandb.sdk.lib.filesystem import StrPath, mkdir_exists_ok
from wandb.sdk.lib.hashutil import B64MD5, ETag, HexMD5, b64_to_hex_id
from wandb.util import FilePathStr, LogicalFilePathStr, URIStr

if TYPE_CHECKING:
    # need this import for type annotations, but want to avoid circular dependency
    import sys

    import wandb.apis.public
    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk import wandb_artifacts
    from wandb.sdk.internal import progress

    if sys.version_info >= (3, 8):
        from typing import Protocol
    else:
        from typing_extensions import Protocol

    class Opener(Protocol):
        def __call__(self, mode: str = ...) -> ContextManager[IO]:
            pass


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
        entries: Optional[Mapping[str, "ArtifactManifestEntry"]] = None,
    ) -> None:
        self.storage_policy = storage_policy
        self.entries = dict(entries) if entries else {}

    def to_manifest_json(self) -> Dict:
        raise NotImplementedError

    def digest(self) -> HexMD5:
        raise NotImplementedError

    def add_entry(self, entry: "ArtifactManifestEntry") -> None:
        if (
            entry.path in self.entries
            and entry.digest != self.entries[entry.path].digest
        ):
            raise ValueError("Cannot add the same path twice: %s" % entry.path)
        self.entries[entry.path] = entry

    def get_entry_by_path(self, path: str) -> Optional["ArtifactManifestEntry"]:
        return self.entries.get(path)

    def get_entries_in_directory(self, directory: str) -> List["ArtifactManifestEntry"]:
        return [
            self.entries[entry_key]
            for entry_key in self.entries
            if entry_key.startswith(
                directory + "/"
            )  # entries use forward slash even for windows
        ]


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


class ArtifactStatusError(AttributeError):
    """Raised when an artifact is in an invalid state for the requested operation."""

    def __init__(
        self,
        artifact: Optional["Artifact"] = None,
        attr: Optional[str] = None,
        msg: str = "Artifact is in an invalid state for the requested operation.",
    ):
        object_name = artifact.__class__.__name__ if artifact else "Artifact"
        method_id = f"{object_name}.{attr}" if attr else object_name
        super().__init__(msg.format(artifact=artifact, attr=attr, method_id=method_id))
        # Follow the same pattern as AttributeError.
        self.obj = artifact
        self.name = attr


class ArtifactNotLoggedError(ArtifactStatusError):
    """Raised for Artifact methods or attributes only available after logging."""

    def __init__(
        self, artifact: Optional["Artifact"] = None, attr: Optional[str] = None
    ):
        super().__init__(
            artifact,
            attr,
            "'{method_id}' used prior to logging artifact or while in offline mode. "
            "Call wait() before accessing logged artifact properties.",
        )


class ArtifactFinalizedError(ArtifactStatusError):
    """Raised for Artifact methods or attributes that can't be changed after logging."""

    def __init__(
        self, artifact: Optional["Artifact"] = None, attr: Optional[str] = None
    ):
        super().__init__(
            artifact,
            attr,
            "'{method_id}' used on logged artifact. Can't add to finalized artifact.",
        )


class Artifact:
    @property
    def id(self) -> Optional[str]:
        """The artifact's ID."""
        raise NotImplementedError

    @property
    def version(self) -> str:
        """The version of this artifact.

        For example, if this is the first version of an artifact, its `version` will be
        'v0'.
        """
        raise NotImplementedError

    @property
    def source_version(self) -> Optional[str]:
        """The artifact's version index under its parent artifact collection.

        A string with the format "v{number}".
        """
        raise NotImplementedError

    @property
    def name(self) -> str:
        """The artifact's name."""
        raise NotImplementedError

    @property
    def type(self) -> str:
        """The artifact's type."""
        raise NotImplementedError

    @property
    def entity(self) -> str:
        """The name of the entity this artifact belongs to."""
        raise NotImplementedError

    @property
    def project(self) -> str:
        """The name of the project this artifact belongs to."""
        raise NotImplementedError

    @property
    def manifest(self) -> ArtifactManifest:
        """The artifact's manifest.

        The manifest lists all of its contents, and can't be changed once the artifact
        has been logged.
        """
        raise NotImplementedError

    @property
    def digest(self) -> str:
        """The logical digest of the artifact.

        The digest is the checksum of the artifact's contents. If an artifact has the
        same digest as the current `latest` version, then `log_artifact` is a no-op.
        """
        raise NotImplementedError

    @property
    def state(self) -> str:
        """The status of the artifact. One of: "PENDING", "COMMITTED", or "DELETED"."""
        raise NotImplementedError

    @property
    def size(self) -> int:
        """The total size of the artifact in bytes.

        Returns:
            (int): The size in bytes of the artifact. Includes any references tracked by
                this artifact.
        """
        raise NotImplementedError

    @property
    def commit_hash(self) -> str:
        """The hash returned when this artifact was committed.

        Returns:
            (str): The artifact's commit hash which is used in http URLs.
        """
        raise NotImplementedError

    @property
    def description(self) -> Optional[str]:
        """The artifact description.

        Returns:
            (str): Free text that offers a user-set description of the artifact.
        """
        raise NotImplementedError

    @description.setter
    def description(self, desc: Optional[str]) -> None:
        """The artifact description.

        The description is markdown rendered in the UI, so this is a good place to put
        links, etc.

        Arguments:
            desc: Free text that offers a description of the artifact.
        """
        raise NotImplementedError

    @property
    def metadata(self) -> dict:
        """User-defined artifact metadata.

        Returns:
            (dict): Structured data associated with the artifact.
        """
        raise NotImplementedError

    @metadata.setter
    def metadata(self, metadata: dict) -> None:
        """User-defined artifact metadata.

        Metadata set this way will eventually be queryable and plottable in the UI; e.g.
        the class distribution of a dataset.

        Note: There is currently a limit of 100 total keys.

        Arguments:
            metadata: (dict) Structured data associated with the artifact.
        """
        raise NotImplementedError

    @property
    def aliases(self) -> List[str]:
        """The aliases associated with this artifact.

        The list is mutable and calling `save()` will persist all alias changes.
        """
        raise NotImplementedError

    @aliases.setter
    def aliases(self, aliases: List[str]) -> None:
        """The aliases associated with this artifact."""
        raise NotImplementedError

    def used_by(self) -> List["wandb.apis.public.Run"]:
        """Get a list of the runs that have used this artifact."""
        raise NotImplementedError

    def logged_by(self) -> "wandb.apis.public.Run":
        """Get the run that first logged this artifact."""
        raise NotImplementedError

    def new_file(
        self, name: str, mode: str = "w", encoding: Optional[str] = None
    ) -> ContextManager[IO]:
        """Open a new temporary file that will be automatically added to the artifact.

        Arguments:
            name: (str) The name of the new file being added to the artifact.
            mode: (str, optional) The mode in which to open the new file.
            encoding: (str, optional) The encoding in which to open the new file.

        Examples:
            ```
            artifact = wandb.Artifact('my_data', type='dataset')
            with artifact.new_file('hello.txt') as f:
                f.write('hello!')
            wandb.log_artifact(artifact)
            ```

        Returns:
            (file): A new file object that can be written to. Upon closing,
                the file will be automatically added to the artifact.

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.
        """
        raise NotImplementedError

    def add_file(
        self,
        local_path: str,
        name: Optional[str] = None,
        is_tmp: Optional[bool] = False,
    ) -> ArtifactManifestEntry:
        """Add a local file to the artifact.

        Arguments:
            local_path: (str) The path to the file being added.
            name: (str, optional) The path within the artifact to use for the file being
                added. Defaults to the basename of the file.
            is_tmp: (bool, optional) If true, then the file is renamed deterministically
                to avoid collisions. (default: False)

        Examples:
            Add a file without an explicit name:
            ```
            # Add as `file.txt'
            artifact.add_file('path/to/file.txt')
            ```

            Add a file with an explicit name:
            ```
            # Add as 'new/path/file.txt'
            artifact.add_file('path/to/file.txt', name='new/path/file.txt')
            ```

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.

        Returns:
            ArtifactManifestEntry: the added manifest entry

        """
        raise NotImplementedError

    def add_dir(self, local_path: str, name: Optional[str] = None) -> None:
        """Add a local directory to the artifact.

        Arguments:
            local_path: (str) The path to the directory being added.
            name: (str, optional) The path within the artifact to use for the directory
                being added. Defaults to the root of the artifact.

        Examples:
            Add a directory without an explicit name:
            ```
            # All files in `my_dir/` are added at the root of the artifact.
            artifact.add_dir('my_dir/')
            ```

            Add a directory and name it explicitly:
            ```
            # All files in `my_dir/` are added under `destination/`.
            artifact.add_dir('my_dir/', name='destination')
            ```

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.

        Returns:
            None
        """
        raise NotImplementedError

    def add_reference(
        self,
        uri: Union[ArtifactManifestEntry, str],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        """Add a reference denoted by a URI to the artifact.

        Unlike adding files or directories, references are NOT uploaded to W&B. However,
        artifact methods such as `download()` can be used regardless of whether the
        artifact contains references or uploaded files.

        By default, W&B offers special handling for the following schemes:

        - http(s): The size and digest of the file will be inferred by the
          `Content-Length` and the `ETag` response headers returned by the server.
        - s3: The checksum and size will be pulled from the object metadata. If bucket
          versioning is enabled, then the version ID is also tracked.
        - gs: The checksum and size will be pulled from the object metadata. If bucket
          versioning is enabled, then the version ID is also tracked.
        - file: The checksum and size will be pulled from the file system. This scheme
          is useful if you have an NFS share or other externally mounted volume
          containing files you wish to track but not necessarily upload.

        For any other scheme, the digest is just a hash of the URI and the size is left
        blank.

        Arguments:
            uri: (str) The URI path of the reference to add. Can be an object returned
            from
                Artifact.get_path to store a reference to another artifact's entry.
            name: (str) The path within the artifact to place the contents of this
            reference checksum: (bool, optional) Whether or not to checksum the
            resource(s) located at the
                reference URI. Checksumming is strongly recommended as it enables
                automatic integrity validation, however it can be disabled to speed up
                artifact creation. (default: True)
            max_objects: (int, optional) The maximum number of objects to consider when
            adding a
                reference that points to directory or bucket store prefix. For S3 and
                GCS, this limit is 10,000 by default but is uncapped for other URI
                schemes. (default: None)

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.

        Returns:
            List[ArtifactManifestEntry]: The added manifest entries.

        Examples:
        Add an HTTP link:
        ```python
        # Adds `file.txt` to the root of the artifact as a reference.
        artifact.add_reference("http://myserver.com/file.txt")
        ```

        Add an S3 prefix without an explicit name:
        ```python
        # All objects under `prefix/` will be added at the root of the artifact.
        artifact.add_reference("s3://mybucket/prefix")
        ```

        Add a GCS prefix with an explicit name:
        ```python
        # All objects under `prefix/` will be added under `path/` at the artifact root.
        artifact.add_reference("gs://mybucket/prefix", name="path")
        ```
        """
        raise NotImplementedError

    def add(self, obj: WBValue, name: str) -> ArtifactManifestEntry:
        """Add wandb.WBValue `obj` to the artifact.

        ```
        obj = artifact.get(name)
        ```

        Arguments:
            obj: (wandb.WBValue) The object to add. Currently support one of
                Bokeh, JoinedTable, PartitionedTable, Table, Classes, ImageMask,
                BoundingBoxes2D, Audio, Image, Video, Html, Object3D
            name: (str) The path within the artifact to add the object.

        Returns:
            ArtifactManifestEntry: the added manifest entry

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.

        Examples:
            Basic usage
            ```
            artifact = wandb.Artifact('my_table', 'dataset')
            table = wandb.Table(columns=["a", "b", "c"], data=[[i, i*2, 2**i]])
            artifact.add(table, "my_table")

            wandb.log_artifact(artifact)
            ```

            Retrieve an object:
            ```
            artifact = wandb.use_artifact('my_table:latest')
            table = artifact.get("my_table")
            ```
        """
        raise NotImplementedError

    def get_path(self, name: str) -> ArtifactManifestEntry:
        """Get the path to the file located at the artifact relative `name`.

        Arguments:
            name: (str) The artifact relative name to get

        Raises:
            ArtifactNotLoggedError: if the artifact isn't logged or the run is offline

        Examples:
            Basic usage
            ```
            # Run logging the artifact
            with wandb.init() as r:
                artifact = wandb.Artifact('my_dataset', type='dataset')
                artifact.add_file('path/to/file.txt')
                wandb.log_artifact(artifact)

            # Run using the artifact
            with wandb.init() as r:
                artifact = r.use_artifact('my_dataset:latest')
                path = artifact.get_path('file.txt')

                # Can now download 'file.txt' directly:
                path.download()
            ```
        """
        raise NotImplementedError

    def get(self, name: str) -> WBValue:
        """Get the WBValue object located at the artifact relative `name`.

        Arguments:
            name: (str) The artifact relative name to get

        Raises:
            ArtifactNotLoggedError: if the artifact isn't logged or the run is offline

        Examples:
            Basic usage
            ```
            # Run logging the artifact
            with wandb.init() as r:
                artifact = wandb.Artifact('my_dataset', type='dataset')
                table = wandb.Table(columns=["a", "b", "c"], data=[[i, i*2, 2**i]])
                artifact.add(table, "my_table")
                wandb.log_artifact(artifact)

            # Run using the artifact
            with wandb.init() as r:
                artifact = r.use_artifact('my_dataset:latest')
                table = r.get('my_table')
            ```
        """
        raise NotImplementedError

    def download(
        self, root: Optional[str] = None, recursive: bool = False
    ) -> FilePathStr:
        """Download the contents of the artifact to the specified root directory.

        NOTE: Any existing files at `root` are left untouched. Explicitly delete
        root before calling `download` if you want the contents of `root` to exactly
        match the artifact.

        Arguments:
            root: (str, optional) The directory in which to download this artifact's files.
            recursive: (bool, optional) If true, then all dependent artifacts are eagerly
                downloaded. Otherwise, the dependent artifacts are downloaded as needed.

        Returns:
            (str): The path to the downloaded contents.
        """
        raise NotImplementedError

    def checkout(self, root: Optional[str] = None) -> str:
        """Replace the specified root directory with the contents of the artifact.

        WARNING: This will DELETE all files in `root` that are not included in the
        artifact.

        Arguments:
            root: (str, optional) The directory to replace with this artifact's files.

        Returns:
           (str): The path to the checked out contents.
        """
        raise NotImplementedError

    def verify(self, root: Optional[str] = None) -> bool:
        """Verify that the actual contents of an artifact match the manifest.

        All files in the directory are checksummed and the checksums are then
        cross-referenced against the artifact's manifest.

        NOTE: References are not verified.

        Arguments:
            root: (str, optional) The directory to verify. If None
                artifact will be downloaded to './artifacts/self.name/'

        Raises:
            (ValueError): If the verification fails.
        """
        raise NotImplementedError

    def save(self) -> None:
        """Persist any changes made to the artifact.

        Returns:
            None
        """
        raise NotImplementedError

    def link(self, target_path: str, aliases: Optional[List[str]] = None) -> None:
        """Link this artifact to a portfolio (a promoted collection of artifacts), with aliases.

        Arguments:
            target_path: (str) The path to the portfolio. It must take the form
                {portfolio}, {project}/{portfolio} or {entity}/{project}/{portfolio}.
            aliases: (Optional[List[str]]) A list of strings which uniquely
                identifies the artifact inside the specified portfolio.

        Returns:
            None
        """
        raise NotImplementedError

    def delete(self) -> None:
        """Delete this artifact, cleaning up all files associated with it.

        NOTE: Deletion is permanent and CANNOT be undone.

        Returns:
            None
        """
        raise NotImplementedError

    def wait(self) -> "Artifact":
        """Wait for this artifact to finish logging, if needed.

        Returns:
            Artifact
        """
        raise NotImplementedError

    def __getitem__(self, name: str) -> Optional[WBValue]:
        """Get the WBValue object located at the artifact relative `name`.

        Arguments:
            name: (str) The artifact relative name to get

        Raises:
            ArtifactNotLoggedError: if the artifact isn't logged or the run is offline

        Examples:
            Basic usage
            ```
            artifact = wandb.Artifact('my_table', 'dataset')
            table = wandb.Table(columns=["a", "b", "c"], data=[[i, i*2, 2**i]])
            artifact["my_table"] = table

            wandb.log_artifact(artifact)
            ```

            Retrieving an object:
            ```
            artifact = wandb.use_artifact('my_table:latest')
            table = artifact["my_table"]
            ```
        """
        raise NotImplementedError

    def __setitem__(self, name: str, item: WBValue) -> "ArtifactManifestEntry":
        """Add `item` to the artifact at path `name`.

        Arguments:
            name: (str) The path within the artifact to add the object.
            item: (wandb.WBValue) The object to add.

        Returns:
            ArtifactManifestEntry: the added manifest entry

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.

        Examples:
            Basic usage
            ```
            artifact = wandb.Artifact('my_table', 'dataset')
            table = wandb.Table(columns=["a", "b", "c"], data=[[i, i*2, 2**i]])
            artifact["my_table"] = table

            wandb.log_artifact(artifact)
            ```

            Retrieving an object:
            ```
            artifact = wandb.use_artifact('my_table:latest')
            table = artifact["my_table"]
            ```
        """
        raise NotImplementedError


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


class ArtifactsCache:
    _TMP_PREFIX = "tmp"

    def __init__(self, cache_dir: StrPath) -> None:
        self._cache_dir = cache_dir
        mkdir_exists_ok(self._cache_dir)
        self._md5_obj_dir = os.path.join(self._cache_dir, "obj", "md5")
        self._etag_obj_dir = os.path.join(self._cache_dir, "obj", "etag")
        self._artifacts_by_id: Dict[str, Artifact] = {}
        self._random = random.Random()
        self._random.seed()
        self._artifacts_by_client_id: Dict[str, "wandb_artifacts.Artifact"] = {}

    def check_md5_obj_path(
        self, b64_md5: B64MD5, size: int
    ) -> Tuple[FilePathStr, bool, "Opener"]:
        hex_md5 = b64_to_hex_id(b64_md5)
        path = os.path.join(self._cache_dir, "obj", "md5", hex_md5[:2], hex_md5[2:])
        opener = self._cache_opener(path)
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return FilePathStr(path), True, opener
        mkdir_exists_ok(os.path.dirname(path))
        return FilePathStr(path), False, opener

    # TODO(spencerpearson): this method at least needs its signature changed.
    # An ETag is not (necessarily) a checksum.
    def check_etag_obj_path(
        self,
        url: URIStr,
        etag: ETag,
        size: int,
    ) -> Tuple[FilePathStr, bool, "Opener"]:
        hexhash = hashlib.sha256(
            hashlib.sha256(url.encode("utf-8")).digest()
            + hashlib.sha256(etag.encode("utf-8")).digest()
        ).hexdigest()
        path = os.path.join(self._cache_dir, "obj", "etag", hexhash[:2], hexhash[2:])
        opener = self._cache_opener(path)
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return FilePathStr(path), True, opener
        mkdir_exists_ok(os.path.dirname(path))
        return FilePathStr(path), False, opener

    def get_artifact(self, artifact_id: str) -> Optional["Artifact"]:
        return self._artifacts_by_id.get(artifact_id)

    def store_artifact(self, artifact: "Artifact") -> None:
        if not artifact.id:
            raise ArtifactNotLoggedError(artifact, "store_artifact")
        self._artifacts_by_id[artifact.id] = artifact

    def get_client_artifact(
        self, client_id: str
    ) -> Optional["wandb_artifacts.Artifact"]:
        return self._artifacts_by_client_id.get(client_id)

    def store_client_artifact(self, artifact: "wandb_artifacts.Artifact") -> None:
        self._artifacts_by_client_id[artifact._client_id] = artifact

    def cleanup(self, target_size: int) -> int:
        bytes_reclaimed = 0
        paths = {}
        total_size = 0
        for root, _, files in os.walk(self._cache_dir):
            for file in files:
                try:
                    path = str(os.path.join(root, file))
                    stat = os.stat(path)

                    if file.startswith(ArtifactsCache._TMP_PREFIX):
                        os.remove(path)
                        bytes_reclaimed += stat.st_size
                        continue
                except OSError:
                    continue
                paths[path] = stat
                total_size += stat.st_size

        sorted_paths = sorted(paths.items(), key=lambda x: x[1].st_atime)
        for path, stat in sorted_paths:
            if total_size < target_size:
                return bytes_reclaimed

            try:
                os.remove(path)
            except OSError:
                pass

            total_size -= stat.st_size
            bytes_reclaimed += stat.st_size
        return bytes_reclaimed

    def _cache_opener(self, path: StrPath) -> "Opener":
        @contextlib.contextmanager
        def helper(mode: str = "w") -> Generator[IO, None, None]:
            if "a" in mode:
                raise ValueError("Appending to cache files is not supported")

            dirname = os.path.dirname(path)
            tmp_file = os.path.join(
                dirname,
                "%s_%s"
                % (
                    ArtifactsCache._TMP_PREFIX,
                    util.rand_alphanumeric(length=8, rand=self._random),
                ),
            )
            with util.fsync_open(tmp_file, mode=mode) as f:
                yield f

            try:
                # Use replace where we can, as it implements an atomic
                # move on most platforms. If it doesn't exist, we have
                # to use rename which isn't atomic in all cases but there
                # isn't a better option.
                #
                # The atomic replace is important in the event multiple processes
                # attempt to write to / read from the cache at the same time. Each
                # writer firsts stages its writes to a temporary file in the cache.
                # Once it is finished, we issue an atomic replace operation to update
                # the cache. Although this can result in redundant downloads, this
                # guarantees that readers can NEVER read incomplete files from the
                # cache.
                #
                # IMPORTANT: Replace is NOT atomic across different filesystems. This why
                # it is critical that the temporary files sit directly in the cache --
                # they need to be on the same filesystem!
                os.replace(tmp_file, path)
            except AttributeError:
                os.rename(tmp_file, path)

        return helper


_artifacts_cache = None


def get_artifacts_cache() -> ArtifactsCache:
    global _artifacts_cache
    if _artifacts_cache is None:
        cache_dir = os.path.join(env.get_cache_dir(), "artifacts")
        _artifacts_cache = ArtifactsCache(cache_dir)
    return _artifacts_cache


def get_staging_dir() -> FilePathStr:
    path = os.path.join(env.get_data_dir(), "artifacts", "staging")
    mkdir_exists_ok(path)
    return FilePathStr(os.path.abspath(os.path.expanduser(path)))


def get_new_staging_file() -> IO:
    return tempfile.NamedTemporaryFile(dir=get_staging_dir(), delete=False)
