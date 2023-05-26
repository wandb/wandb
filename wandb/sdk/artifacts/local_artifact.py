"""Local (draft) artifact."""
import contextlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import PurePosixPath
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Dict,
    Generator,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)
from urllib.parse import urlparse

import wandb
import wandb.data_types as data_types
from wandb import env, util
from wandb.errors.term import termlog
from wandb.sdk import lib as wandb_lib
from wandb.sdk.artifacts.artifact import Artifact as ArtifactInterface
from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifact_manifests.artifact_manifest_v1 import (
    ArtifactManifestV1,
)
from wandb.sdk.artifacts.artifact_saver import get_staging_dir
from wandb.sdk.artifacts.artifacts_cache import get_artifacts_cache
from wandb.sdk.artifacts.exceptions import (
    ArtifactFinalizedError,
    ArtifactNotLoggedError,
)
from wandb.sdk.artifacts.storage_layout import StorageLayout
from wandb.sdk.artifacts.storage_policies.wandb_storage_policy import WandbStoragePolicy
from wandb.sdk.lib import filesystem, runid
from wandb.sdk.lib.hashutil import B64MD5, b64_to_hex_id, md5_file_b64
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr

if TYPE_CHECKING:
    import wandb.apis.public

ARTIFACT_TMP = tempfile.TemporaryDirectory("wandb-artifacts")


class _AddedObj:
    def __init__(self, entry: ArtifactManifestEntry, obj: data_types.WBValue):
        self.entry = entry
        self.obj = obj


def _normalize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise TypeError(f"metadata must be dict, not {type(metadata)}")
    return cast(
        Dict[str, Any], json.loads(json.dumps(util.json_friendly_val(metadata)))
    )


class Artifact(ArtifactInterface):
    """Flexible and lightweight building block for dataset and model versioning.

    Constructs an empty artifact whose contents can be populated using its
    `add` family of functions. Once the artifact has all the desired files,
    you can call `wandb.log_artifact()` to log it.

    Arguments:
        name: (str) A human-readable name for this artifact, which is how you
            can identify this artifact in the UI or reference it in `use_artifact`
            calls. Names can contain letters, numbers, underscores, hyphens, and
            dots. The name must be unique across a project.
        type: (str) The type of the artifact, which is used to organize and differentiate
            artifacts. Common types include `dataset` or `model`, but you can use any string
            containing letters, numbers, underscores, hyphens, and dots.
        description: (str, optional) Free text that offers a description of the artifact. The
            description is markdown rendered in the UI, so this is a good place to place tables,
            links, etc.
        metadata: (dict, optional) Structured data associated with the artifact,
            for example class distribution of a dataset. This will eventually be queryable
            and plottable in the UI. There is a hard limit of 100 total keys.

    Examples:
        Basic usage
        ```
        wandb.init()

        artifact = wandb.Artifact('mnist', type='dataset')
        artifact.add_dir('mnist/')
        wandb.log_artifact(artifact)
        ```

    Returns:
        An `Artifact` object.
    """

    _added_objs: Dict[int, _AddedObj]
    _added_local_paths: Dict[str, ArtifactManifestEntry]
    _distributed_id: Optional[str]
    _metadata: dict
    _logged_artifact: Optional[ArtifactInterface]
    _incremental: bool
    _client_id: str

    def __init__(
        self,
        name: str,
        type: str,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        incremental: Optional[bool] = None,
        use_as: Optional[str] = None,
    ) -> None:
        if not re.match(r"^[a-zA-Z0-9_\-.]+$", name):
            raise ValueError(
                "Artifact name may only contain alphanumeric characters, dashes, underscores, and dots. "
                'Invalid name: "%s"' % name
            )
        if type == "job" or type.startswith("wandb-"):
            raise ValueError(
                "Artifact types 'job' and 'wandb-*' are reserved for internal use. "
                "Please use a different type."
            )

        metadata = _normalize_metadata(metadata)
        # TODO: this shouldn't be a property of the artifact. It's a more like an
        # argument to log_artifact.
        storage_layout = StorageLayout.V2
        if env.get_use_v1_artifacts():
            storage_layout = StorageLayout.V1

        self._storage_policy = WandbStoragePolicy(
            config={
                "storageLayout": storage_layout,
                #  TODO: storage region
            }
        )
        self._final = False
        self._digest = ""
        self._file_entries = None
        self._manifest = ArtifactManifestV1(self._storage_policy)
        self._cache = get_artifacts_cache()
        self._added_objs = {}
        self._added_local_paths = {}
        # You can write into this directory when creating artifact files
        self._artifact_dir = tempfile.TemporaryDirectory()
        self._type = type
        self._name = name
        self._description = description
        self._metadata = metadata
        self._distributed_id = None
        self._logged_artifact = None
        self._incremental = False
        self._client_id = runid.generate_id(128)
        self._sequence_client_id = runid.generate_id(128)
        self._cache.store_client_artifact(self)
        self._use_as = use_as

        if incremental:
            self._incremental = incremental
            wandb.termwarn("Using experimental arg `incremental`")

    @property
    def id(self) -> Optional[str]:
        if self._logged_artifact:
            return self._logged_artifact.id

        # The artifact hasn't been saved so an ID doesn't exist yet.
        return None

    @property
    def entity(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.entity
        raise ArtifactNotLoggedError(self, "entity")

    @property
    def project(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.project
        raise ArtifactNotLoggedError(self, "project")

    @property
    def name(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.name
        return self._name

    @property
    def version(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.version
        raise ArtifactNotLoggedError(self, "version")

    @property
    def source_entity(self) -> str:
        return self.entity

    @property
    def source_project(self) -> str:
        return self.project

    @property
    def source_name(self) -> str:
        return self.name

    @property
    def source_version(self) -> str:
        return self.version

    @property
    def manifest(self) -> ArtifactManifest:
        if self._logged_artifact:
            return self._logged_artifact.manifest

        self.finalize()
        return self._manifest

    @property
    def digest(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.digest

        self.finalize()
        # Digest will be none if the artifact hasn't been saved yet.
        return self._digest

    @property
    def type(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.type

        return self._type

    @property
    def state(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.state

        return "PENDING"

    @property
    def size(self) -> int:
        if self._logged_artifact:
            return self._logged_artifact.size
        sizes: List[int]
        sizes = []
        for entry in self._manifest.entries:
            e_size = self._manifest.entries[entry].size
            if e_size is not None:
                sizes.append(e_size)
        return sum(sizes)

    @property
    def commit_hash(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.commit_hash

        raise ArtifactNotLoggedError(self, "commit_hash")

    @property
    def description(self) -> Optional[str]:
        if self._logged_artifact:
            return self._logged_artifact.description

        return self._description

    @description.setter
    def description(self, desc: Optional[str]) -> None:
        if self._logged_artifact:
            self._logged_artifact.description = desc
            return

        self._description = desc

    @property
    def metadata(self) -> dict:
        if self._logged_artifact:
            return self._logged_artifact.metadata

        return self._metadata

    @metadata.setter
    def metadata(self, metadata: dict) -> None:
        metadata = _normalize_metadata(metadata)
        if self._logged_artifact:
            self._logged_artifact.metadata = metadata
            return

        self._metadata = metadata

    @property
    def aliases(self) -> List[str]:
        if self._logged_artifact:
            return self._logged_artifact.aliases

        raise ArtifactNotLoggedError(self, "aliases")

    @aliases.setter
    def aliases(self, aliases: List[str]) -> None:
        """Set artifact aliases.

        Arguments:
            aliases: (list) The list of aliases associated with this artifact.
        """
        if self._logged_artifact:
            self._logged_artifact.aliases = aliases
            return

        raise ArtifactNotLoggedError(self, "aliases")

    @property
    def use_as(self) -> Optional[str]:
        return self._use_as

    @property
    def distributed_id(self) -> Optional[str]:
        return self._distributed_id

    @distributed_id.setter
    def distributed_id(self, distributed_id: Optional[str]) -> None:
        self._distributed_id = distributed_id

    @property
    def incremental(self) -> bool:
        return self._incremental

    def used_by(self) -> List["wandb.apis.public.Run"]:
        if self._logged_artifact:
            return self._logged_artifact.used_by()

        raise ArtifactNotLoggedError(self, "used_by")

    def logged_by(self) -> Optional["wandb.apis.public.Run"]:
        if self._logged_artifact:
            return self._logged_artifact.logged_by()

        raise ArtifactNotLoggedError(self, "logged_by")

    @contextlib.contextmanager
    def new_file(
        self, name: str, mode: str = "w", encoding: Optional[str] = None
    ) -> Generator[IO, None, None]:
        self._ensure_can_add()
        path = os.path.join(self._artifact_dir.name, name.lstrip("/"))
        if os.path.exists(path):
            raise ValueError(f"File with name {name!r} already exists at {path!r}")

        filesystem.mkdir_exists_ok(os.path.dirname(path))
        try:
            with util.fsync_open(path, mode, encoding) as f:
                yield f
        except UnicodeEncodeError as e:
            wandb.termerror(
                f"Failed to open the provided file (UnicodeEncodeError: {e}). Please provide the proper encoding."
            )
            raise e
        self.add_file(path, name=name)

    def add_file(
        self,
        local_path: str,
        name: Optional[str] = None,
        is_tmp: Optional[bool] = False,
    ) -> ArtifactManifestEntry:
        self._ensure_can_add()
        if not os.path.isfile(local_path):
            raise ValueError("Path is not a file: %s" % local_path)

        name = LogicalPath(name or os.path.basename(local_path))
        digest = md5_file_b64(local_path)

        if is_tmp:
            file_path, file_name = os.path.split(name)
            file_name_parts = file_name.split(".")
            file_name_parts[0] = b64_to_hex_id(digest)[:20]
            name = os.path.join(file_path, ".".join(file_name_parts))

        return self._add_local_file(name, local_path, digest=digest)

    def add_dir(self, local_path: str, name: Optional[str] = None) -> None:
        self._ensure_can_add()
        if not os.path.isdir(local_path):
            raise ValueError("Path is not a directory: %s" % local_path)

        termlog(
            "Adding directory to artifact (%s)... "
            % os.path.join(".", os.path.normpath(local_path)),
            newline=False,
        )
        start_time = time.time()

        paths = []
        for dirpath, _, filenames in os.walk(local_path, followlinks=True):
            for fname in filenames:
                physical_path = os.path.join(dirpath, fname)
                logical_path = os.path.relpath(physical_path, start=local_path)
                if name is not None:
                    logical_path = os.path.join(name, logical_path)
                paths.append((logical_path, physical_path))

        def add_manifest_file(log_phy_path: Tuple[str, str]) -> None:
            logical_path, physical_path = log_phy_path
            self._add_local_file(logical_path, physical_path)

        import multiprocessing.dummy  # this uses threads

        num_threads = 8
        pool = multiprocessing.dummy.Pool(num_threads)
        pool.map(add_manifest_file, paths)
        pool.close()
        pool.join()

        termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)

    def add_reference(
        self,
        uri: Union[ArtifactManifestEntry, str],
        name: Optional[StrPath] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        self._ensure_can_add()
        if name is not None:
            name = LogicalPath(name)

        # This is a bit of a hack, we want to check if the uri is a of the type
        # ArtifactManifestEntry which is a private class returned by Artifact.get_path in
        # wandb/apis/public.py. If so, then recover the reference URL.
        if isinstance(uri, ArtifactManifestEntry):
            ref_url_fn = uri.ref_url
            uri_str = ref_url_fn()
        elif isinstance(uri, str):
            uri_str = uri
        url = urlparse(str(uri_str))
        if not url.scheme:
            raise ValueError(
                "References must be URIs. To reference a local file, use file://"
            )

        manifest_entries = self._storage_policy.store_reference(
            self,
            URIStr(uri_str),
            name=name,
            checksum=checksum,
            max_objects=max_objects,
        )
        for entry in manifest_entries:
            self._manifest.add_entry(entry)

        return manifest_entries

    def add(self, obj: data_types.WBValue, name: StrPath) -> ArtifactManifestEntry:
        self._ensure_can_add()
        name = LogicalPath(name)

        # This is a "hack" to automatically rename tables added to
        # the wandb /media/tables directory to their sha-based name.
        # TODO: figure out a more appropriate convention.
        is_tmp_name = name.startswith("media/tables")

        # Validate that the object is one of the correct wandb.Media types
        # TODO: move this to checking subclass of wandb.Media once all are
        # generally supported
        allowed_types = [
            data_types.Bokeh,
            data_types.JoinedTable,
            data_types.PartitionedTable,
            data_types.Table,
            data_types.Classes,
            data_types.ImageMask,
            data_types.BoundingBoxes2D,
            data_types.Audio,
            data_types.Image,
            data_types.Video,
            data_types.Html,
            data_types.Object3D,
            data_types.Molecule,
            data_types._SavedModel,
        ]

        if not any(isinstance(obj, t) for t in allowed_types):
            raise ValueError(
                "Found object of type {}, expected one of {}.".format(
                    obj.__class__, allowed_types
                )
            )

        obj_id = id(obj)
        if obj_id in self._added_objs:
            return self._added_objs[obj_id].entry

        # If the object is coming from another artifact, save it as a reference
        ref_path = obj._get_artifact_entry_ref_url()
        if ref_path is not None:
            return self.add_reference(ref_path, type(obj).with_suffix(name))[0]

        val = obj.to_json(self)
        name = obj.with_suffix(name)
        entry = self._manifest.get_entry_by_path(name)
        if entry is not None:
            return entry

        def do_write(f: IO) -> None:
            import json

            # TODO: Do we need to open with utf-8 codec?
            f.write(json.dumps(val, sort_keys=True))

        if is_tmp_name:
            file_path = os.path.join(ARTIFACT_TMP.name, str(id(self)), name)
            folder_path, _ = os.path.split(file_path)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
            with open(file_path, "w") as tmp_f:
                do_write(tmp_f)
        else:
            with self.new_file(name) as f:
                file_path = f.name
                do_write(f)

        # Note, we add the file from our temp directory.
        # It will be added again later on finalize, but succeed since
        # the checksum should match
        entry = self.add_file(file_path, name, is_tmp_name)
        self._added_objs[obj_id] = _AddedObj(entry, obj)
        if obj._artifact_target is None:
            obj._set_artifact_target(self, entry.path)

        if is_tmp_name:
            if os.path.exists(file_path):
                os.remove(file_path)

        return entry

    def remove(self, item: Union[StrPath, "ArtifactManifestEntry"]) -> None:
        if self._logged_artifact:
            raise ArtifactFinalizedError(self, "remove")

        if isinstance(item, ArtifactManifestEntry):
            self._manifest.remove_entry(item)
            return

        path = str(PurePosixPath(item))
        entry = self._manifest.get_entry_by_path(path)
        if entry:
            self._manifest.remove_entry(entry)
            return

        entries = self._manifest.get_entries_in_directory(path)
        if not entries:
            raise FileNotFoundError(f"No such file or directory: {path}")
        for entry in entries:
            self._manifest.remove_entry(entry)

    def get_path(self, name: StrPath) -> ArtifactManifestEntry:
        if self._logged_artifact:
            return self._logged_artifact.get_path(name)

        raise ArtifactNotLoggedError(self, "get_path")

    def get(self, name: str) -> Optional[data_types.WBValue]:
        if self._logged_artifact:
            return self._logged_artifact.get(name)

        raise ArtifactNotLoggedError(self, "get")

    def download(
        self, root: Optional[str] = None, recursive: bool = False
    ) -> FilePathStr:
        if self._logged_artifact:
            return self._logged_artifact.download(root=root, recursive=recursive)

        raise ArtifactNotLoggedError(self, "download")

    def checkout(self, root: Optional[str] = None) -> str:
        if self._logged_artifact:
            return self._logged_artifact.checkout(root=root)

        raise ArtifactNotLoggedError(self, "checkout")

    def verify(self, root: Optional[str] = None) -> None:
        if self._logged_artifact:
            return self._logged_artifact.verify(root=root)

        raise ArtifactNotLoggedError(self, "verify")

    def save(
        self,
        project: Optional[str] = None,
        settings: Optional["wandb.wandb_sdk.wandb_settings.Settings"] = None,
    ) -> None:
        """Persist any changes made to the artifact.

        If currently in a run, that run will log this artifact. If not currently in a
        run, a run of type "auto" will be created to track this artifact.

        Arguments:
            project: (str, optional) A project to use for the artifact in the case that
            a run is not already in context settings: (wandb.Settings, optional) A
            settings object to use when initializing an automatic run. Most commonly
            used in testing harness.

        Returns:
            None
        """
        if self._incremental:
            with wandb_lib.telemetry.context() as tel:
                tel.feature.artifact_incremental = True

        if self._logged_artifact:
            return self._logged_artifact.save()
        else:
            if wandb.run is None:
                if settings is None:
                    settings = wandb.Settings(silent="true")
                with wandb.init(
                    project=project, job_type="auto", settings=settings
                ) as run:
                    # redoing this here because in this branch we know we didn't
                    # have the run at the beginning of the method
                    if self._incremental:
                        with wandb_lib.telemetry.context(run=run) as tel:
                            tel.feature.artifact_incremental = True
                    run.log_artifact(self)
            else:
                wandb.run.log_artifact(self)

    def delete(self, delete_aliases: bool = False) -> None:
        if self._logged_artifact:
            return self._logged_artifact.delete(delete_aliases=delete_aliases)

        raise ArtifactNotLoggedError(self, "delete")

    def wait(self, timeout: Optional[int] = None) -> ArtifactInterface:
        """Wait for an artifact to finish logging.

        Arguments:
            timeout: (int, optional) Wait up to this long.
        """
        if self._logged_artifact:
            return self._logged_artifact.wait(timeout)  # type: ignore [call-arg]

        raise ArtifactNotLoggedError(self, "wait")

    def get_added_local_path_name(self, local_path: str) -> Optional[str]:
        """Get the artifact relative name of a file added by a local filesystem path.

        Arguments:
            local_path: (str) The local path to resolve into an artifact relative name.

        Returns:
            str: The artifact relative name.

        Examples:
            Basic usage
            ```
            artifact = wandb.Artifact('my_dataset', type='dataset')
            artifact.add_file('path/to/file.txt', name='artifact/path/file.txt')

            # Returns `artifact/path/file.txt`:
            name = artifact.get_added_local_path_name('path/to/file.txt')
            ```
        """
        entry = self._added_local_paths.get(local_path, None)
        if entry is None:
            return None
        return entry.path

    def finalize(self) -> None:
        """Mark this artifact as final, disallowing further modifications.

        This happens automatically when calling `log_artifact`.

        Returns:
            None
        """
        if self._final:
            return self._file_entries

        # mark final after all files are added
        self._final = True
        self._digest = self._manifest.digest()

    def json_encode(self) -> Dict[str, Any]:
        if not self._logged_artifact:
            raise ArtifactNotLoggedError(self, "json_encode")
        return util.artifact_to_json(self)

    def _ensure_can_add(self) -> None:
        if self._final:
            raise ArtifactFinalizedError(artifact=self)

    def _add_local_file(
        self, name: StrPath, path: StrPath, digest: Optional[B64MD5] = None
    ) -> ArtifactManifestEntry:
        with tempfile.NamedTemporaryFile(dir=get_staging_dir(), delete=False) as f:
            staging_path = f.name
            shutil.copyfile(path, staging_path)
            os.chmod(staging_path, 0o400)

        entry = ArtifactManifestEntry(
            path=name,
            digest=digest or md5_file_b64(staging_path),
            local_path=staging_path,
        )

        self._manifest.add_entry(entry)
        self._added_local_paths[os.fspath(path)] = entry
        return entry
