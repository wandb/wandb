from typing import IO, TYPE_CHECKING, ContextManager, List, Optional, Sequence, Union

import wandb
from wandb.data_types import WBValue
from wandb.util import FilePathStr

if TYPE_CHECKING:
    import wandb.apis.public
    from wandb.sdk.interface.artifacts import ArtifactManifest, ArtifactManifestEntry


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
    def manifest(self) -> "ArtifactManifest":
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
        """Set the description of the artifact.

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
        """Set the aliases associated with this artifact."""
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
    ) -> "ArtifactManifestEntry":
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
        uri: Union["ArtifactManifestEntry", str],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence["ArtifactManifestEntry"]:
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
            List["ArtifactManifestEntry"]: The added manifest entries.

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

    def add(self, obj: WBValue, name: str) -> "ArtifactManifestEntry":
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

    def get_path(self, name: str) -> "ArtifactManifestEntry":
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
        return self.get(name)

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
        return self.add(item, name)
