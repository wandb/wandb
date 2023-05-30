"""Public (saved) artifact."""
import contextlib
import datetime
import json
import os
import platform
import re
import urllib
from functools import partial
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Dict,
    Generator,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
)

import requests

import wandb
from wandb import util
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public import ArtifactFiles, RetryingClient, Run
from wandb.data_types import WBValue
from wandb.env import get_artifact_dir
from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact import Artifact as ArtifactInterface
from wandb.sdk.artifacts.artifact_download_logger import ArtifactDownloadLogger
from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifacts_cache import get_artifacts_cache
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.lib.hashutil import hex_to_b64_id, md5_file_b64
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
    from wandb.sdk.artifacts.local_artifact import Artifact as LocalArtifact

reset_path = util.vendor_setup()

from wandb_gql import gql  # noqa: E402

reset_path()

ARTIFACT_FRAGMENT = """
fragment ArtifactFragment on Artifact {
    id
    digest
    description
    state
    size
    createdAt
    updatedAt
    labels
    metadata
    fileCount
    versionIndex
    aliases {
        artifactCollectionName
        alias
    }
    artifactSequence {
        id
        name
    }
    artifactType {
        id
        name
        project {
            name
            entity {
                name
            }
        }
    }
    commitHash
}
"""


class Artifact(ArtifactInterface):
    """A wandb Artifact.

    An artifact that has been logged, including all its attributes, links to the runs
    that use it, and a link to the run that logged it.

    Examples:
        Basic usage
        ```
        api = wandb.Api()
        artifact = api.artifact('project/artifact:alias')

        # Get information about the artifact...
        artifact.digest
        artifact.aliases
        ```

        Updating an artifact
        ```
        artifact = api.artifact('project/artifact:alias')

        # Update the description
        artifact.description = 'My new description'

        # Selectively update metadata keys
        artifact.metadata["oldKey"] = "new value"

        # Replace the metadata entirely
        artifact.metadata = {"newKey": "new value"}

        # Add an alias
        artifact.aliases.append('best')

        # Remove an alias
        artifact.aliases.remove('latest')

        # Completely replace the aliases
        artifact.aliases = ['replaced']

        # Persist all artifact modifications
        artifact.save()
        ```

        Artifact graph traversal
        ```
        artifact = api.artifact('project/artifact:alias')

        # Walk up and down the graph from an artifact:
        producer_run = artifact.logged_by()
        consumer_runs = artifact.used_by()

        # Walk up and down the graph from a run:
        logged_artifacts = run.logged_artifacts()
        used_artifacts = run.used_artifacts()
        ```

        Deleting an artifact
        ```
        artifact = api.artifact('project/artifact:alias')
        artifact.delete()
        ```
    """

    QUERY = gql(
        """
        query ArtifactWithCurrentManifest(
            $id: ID!,
        ) {
            artifact(id: $id) {
                currentManifest {
                    id
                    file {
                        id
                        directUrl
                    }
                }
                ...ArtifactFragment
            }
        }
        %s
    """
        % ARTIFACT_FRAGMENT
    )

    @classmethod
    def from_id(cls, artifact_id: str, client: RetryingClient) -> Optional["Artifact"]:
        artifact = get_artifacts_cache().get_artifact(artifact_id)
        if artifact is not None:
            assert isinstance(artifact, Artifact)
            return artifact
        response: Mapping[str, Any] = client.execute(
            Artifact.QUERY,
            variable_values={"id": artifact_id},
        )

        if response.get("artifact") is None:
            return None
        p = response.get("artifact", {}).get("artifactType", {}).get("project", {})
        project = p.get("name")  # defaults to None
        entity = p.get("entity", {}).get("name")
        name = "{}:v{}".format(
            response["artifact"]["artifactSequence"]["name"],
            response["artifact"]["versionIndex"],
        )
        artifact = cls(
            client=client,
            entity=entity,
            project=project,
            name=name,
            attrs=response["artifact"],
        )
        index_file_url = response["artifact"]["currentManifest"]["file"]["directUrl"]
        with requests.get(index_file_url) as req:
            req.raise_for_status()
            artifact._manifest = ArtifactManifest.from_manifest_json(
                json.loads(util.ensure_text(req.content))
            )

        artifact._load_dependent_manifests()

        return artifact

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        name: str,
        attrs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.client = client
        self._entity = entity
        self._project = project
        self._name = name
        self._artifact_collection_name = name.split(":")[0]
        self._attrs = attrs or self._load()

        # The entity and project above are taken from the passed-in artifact version path
        # so if the user is pulling an artifact version from an artifact portfolio, the entity/project
        # of that portfolio may be different than the birth entity/project of the artifact version.
        self._source_project = (
            self._attrs.get("artifactType", {}).get("project", {}).get("name")
        )
        self._source_entity = (
            self._attrs.get("artifactType", {})
            .get("project", {})
            .get("entity", {})
            .get("name")
        )
        self._metadata = json.loads(self._attrs.get("metadata") or "{}")
        self._description = self._attrs.get("description", None)
        self._source_name = "{}:v{}".format(
            self._attrs["artifactSequence"]["name"], self._attrs.get("versionIndex")
        )
        self._source_version = "v{}".format(self._attrs.get("versionIndex"))
        # We will only show aliases under the Collection this artifact version is fetched from
        # _aliases will be a mutable copy on which the user can append or remove aliases
        self._aliases: List[str] = [
            a["alias"]
            for a in self._attrs["aliases"]
            if not re.match(r"^v\d+$", a["alias"])
            and a["artifactCollectionName"] == self._artifact_collection_name
        ]
        self._frozen_aliases: List[str] = [a for a in self._aliases]
        self._manifest: Optional[ArtifactManifest] = None
        self._is_downloaded: bool = False
        self._dependent_artifacts: List["Artifact"] = []
        self._download_roots: Set[str] = set()
        get_artifacts_cache().store_artifact(self)

    @property
    def id(self) -> Optional[str]:
        return self._attrs["id"]

    @property
    def entity(self) -> str:
        return self._entity

    @property
    def project(self) -> str:
        return self._project

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        """The artifact's version index under the given artifact collection.

        A string with the format "v{number}".
        """
        for a in self._attrs["aliases"]:
            if a[
                "artifactCollectionName"
            ] == self._artifact_collection_name and util.alias_is_version_index(
                a["alias"]
            ):
                return a["alias"]
        raise NotImplementedError

    @property
    def source_entity(self) -> str:
        return self._source_entity

    @property
    def source_project(self) -> str:
        return self._source_project

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def source_version(self) -> str:
        """The artifact's version index under its parent artifact collection.

        A string with the format "v{number}".
        """
        return self._source_version

    @property
    def file_count(self) -> int:
        return self._attrs["fileCount"]

    @property
    def metadata(self) -> dict:
        return self._metadata

    @metadata.setter
    def metadata(self, metadata: dict) -> None:
        self._metadata = metadata

    @property
    def manifest(self) -> ArtifactManifest:
        return self._load_manifest()

    @property
    def digest(self) -> str:
        return self._attrs["digest"]

    @property
    def state(self) -> str:
        return self._attrs["state"]

    @property
    def size(self) -> int:
        return self._attrs["size"]

    @property
    def created_at(self) -> str:
        """The time at which the artifact was created."""
        return self._attrs["createdAt"]

    @property
    def updated_at(self) -> str:
        """The time at which the artifact was last updated."""
        return self._attrs["updatedAt"] or self._attrs["createdAt"]

    @property
    def description(self) -> Optional[str]:
        return self._description

    @description.setter
    def description(self, desc: Optional[str]) -> None:
        self._description = desc

    @property
    def type(self) -> str:
        return self._attrs["artifactType"]["name"]

    @property
    def commit_hash(self) -> str:
        return self._attrs.get("commitHash", "")

    @property
    def aliases(self) -> List[str]:
        """The aliases associated with this artifact.

        Returns:
            List[str]: The aliases associated with this artifact.

        """
        return self._aliases

    @aliases.setter
    def aliases(self, aliases: List[str]) -> None:
        for alias in aliases:
            if any(char in alias for char in ["/", ":"]):
                raise ValueError(
                    'Invalid alias "%s", slashes and colons are disallowed' % alias
                )
        self._aliases = aliases

    @staticmethod
    def expected_type(
        client: RetryingClient, name: str, entity_name: str, project_name: str
    ) -> Optional[str]:
        """Returns the expected type for a given artifact name and project."""
        query = gql(
            """
        query ArtifactType(
            $entityName: String,
            $projectName: String,
            $name: String!
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifact(name: $name) {
                    artifactType {
                        name
                    }
                }
            }
        }
        """
        )
        if ":" not in name:
            name += ":latest"

        response = client.execute(
            query,
            variable_values={
                "entityName": entity_name,
                "projectName": project_name,
                "name": name,
            },
        )

        project = response.get("project")
        if project is not None:
            artifact = project.get("artifact")
            if artifact is not None:
                artifact_type = artifact.get("artifactType")
                if artifact_type is not None:
                    return artifact_type.get("name")

        return None

    @property
    def _use_as(self) -> Optional[str]:
        return self._attrs.get("_use_as")

    @_use_as.setter
    def _use_as(self, use_as: Optional[str]) -> None:
        self._attrs["_use_as"] = use_as

    @normalize_exceptions
    def link(self, target_path: str, aliases: Optional[List[str]] = None) -> None:
        if ":" in target_path:
            raise ValueError(
                f"target_path {target_path} cannot contain `:` because it is not an alias."
            )

        portfolio, project, entity = util._parse_entity_project_item(target_path)
        aliases = util._resolve_aliases(aliases)

        run_entity = wandb.run.entity if wandb.run else None
        run_project = wandb.run.project if wandb.run else None
        entity = entity or run_entity or self.entity
        project = project or run_project or self.project

        mutation = gql(
            """
            mutation LinkArtifact($artifactID: ID!, $artifactPortfolioName: String!, $entityName: String!, $projectName: String!, $aliases: [ArtifactAliasInput!]) {
    linkArtifact(input: {artifactID: $artifactID, artifactPortfolioName: $artifactPortfolioName,
        entityName: $entityName,
        projectName: $projectName,
        aliases: $aliases
    }) {
            versionIndex
    }
}
        """
        )
        self.client.execute(
            mutation,
            variable_values={
                "artifactID": self.id,
                "artifactPortfolioName": portfolio,
                "entityName": entity,
                "projectName": project,
                "aliases": [
                    {"alias": alias, "artifactCollectionName": portfolio}
                    for alias in aliases
                ],
            },
        )

    @normalize_exceptions
    def delete(self, delete_aliases: bool = False) -> None:
        """Delete an artifact and its files.

        Examples:
            Delete all the "model" artifacts a run has logged:
            ```
            runs = api.runs(path="my_entity/my_project")
            for run in runs:
                for artifact in run.logged_artifacts():
                    if artifact.type == "model":
                        artifact.delete(delete_aliases=True)
            ```

        Arguments:
            delete_aliases: (bool) If true, deletes all aliases associated with the artifact.
                Otherwise, this raises an exception if the artifact has existing aliases.
        """
        mutation = gql(
            """
        mutation DeleteArtifact($artifactID: ID!, $deleteAliases: Boolean) {
            deleteArtifact(input: {
                artifactID: $artifactID
                deleteAliases: $deleteAliases
            }) {
                artifact {
                    id
                }
            }
        }
        """
        )
        self.client.execute(
            mutation,
            variable_values={
                "artifactID": self.id,
                "deleteAliases": delete_aliases,
            },
        )

    @contextlib.contextmanager
    def new_file(
        self, name: str, mode: str = "w", encoding: Optional[str] = None
    ) -> Generator[IO, None, None]:
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def add_file(
        self,
        local_path: str,
        name: Optional[str] = None,
        is_tmp: Optional[bool] = False,
    ) -> "ArtifactManifestEntry":
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def add_dir(self, local_path: str, name: Optional[str] = None) -> None:
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def add_reference(
        self,
        uri: Union["ArtifactManifestEntry", str],
        name: Optional[StrPath] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence["ArtifactManifestEntry"]:
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def add(self, obj: WBValue, name: StrPath) -> "ArtifactManifestEntry":
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def remove(self, item: Union[str, "os.PathLike", "ArtifactManifestEntry"]) -> None:
        raise ValueError("Cannot remove files from an artifact once it has been saved")

    def _add_download_root(self, dir_path: str) -> None:
        """Make `dir_path` a root directory for this artifact."""
        self._download_roots.add(os.path.abspath(dir_path))

    def _is_download_root(self, dir_path: str) -> bool:
        """Determine if `dir_path` is a root directory for this artifact."""
        return dir_path in self._download_roots

    def _local_path_to_name(self, file_path: str) -> Optional[str]:
        """Convert a local file path to a path entry in the artifact."""
        abs_file_path = os.path.abspath(file_path)
        abs_file_parts = abs_file_path.split(os.sep)
        for i in range(len(abs_file_parts) + 1):
            if self._is_download_root(os.path.join(os.sep, *abs_file_parts[:i])):
                return os.path.join(*abs_file_parts[i:])
        return None

    def _get_obj_entry(
        self, name: str
    ) -> Tuple[Optional["ArtifactManifestEntry"], Optional[Type[WBValue]]]:
        """Return an object entry by name, handling any type suffixes.

        When objects are added with `.add(obj, name)`, the name is typically changed to
        include the suffix of the object type when serializing to JSON. So we need to be
        able to resolve a name, without tasking the user with appending .THING.json.
        This method returns an entry if it exists by a suffixed name.

        Args:
            name: (str) name used when adding
        """
        self._load_manifest()

        type_mapping = WBValue.type_mapping()
        for artifact_type_str in type_mapping:
            wb_class = type_mapping[artifact_type_str]
            wandb_file_name = wb_class.with_suffix(name)
            entry = self.manifest.entries.get(wandb_file_name)
            if entry is not None:
                return entry, wb_class
        return None, None

    def get_path(self, name: StrPath) -> "ArtifactManifestEntry":
        name = LogicalPath(name)
        manifest = self._load_manifest()
        entry = manifest.entries.get(name) or self._get_obj_entry(name)[0]
        if entry is None:
            raise KeyError("Path not contained in artifact: %s" % name)
        entry._parent_artifact = self
        return entry

    def get(self, name: str) -> Optional[WBValue]:
        entry, wb_class = self._get_obj_entry(name)
        if entry is None or wb_class is None:
            return None
        # If the entry is a reference from another artifact, then get it directly from that artifact
        if self._manifest_entry_is_artifact_reference(entry):
            artifact = self._get_ref_artifact_from_entry(entry)
            return artifact.get(util.uri_from_path(entry.ref))

        # Special case for wandb.Table. This is intended to be a short term optimization.
        # Since tables are likely to download many other assets in artifact(s), we eagerly download
        # the artifact using the parallelized `artifact.download`. In the future, we should refactor
        # the deserialization pattern such that this special case is not needed.
        if wb_class == wandb.Table:
            self.download(recursive=True)

        # Get the ArtifactManifestEntry
        item = self.get_path(entry.path)
        item_path = item.download()

        # Load the object from the JSON blob
        result = None
        json_obj = {}
        with open(item_path) as file:
            json_obj = json.load(file)
        result = wb_class.from_json(json_obj, self)
        result._set_artifact_source(self, name)
        return result

    def download(
        self, root: Optional[str] = None, recursive: bool = False
    ) -> FilePathStr:
        dirpath = root or self._default_root()
        self._add_download_root(dirpath)
        manifest = self._load_manifest()
        nfiles = len(manifest.entries)
        size = sum(e.size or 0 for e in manifest.entries.values())
        log = False
        if nfiles > 5000 or size > 50 * 1024 * 1024:
            log = True
            termlog(
                "Downloading large artifact {}, {:.2f}MB. {} files... ".format(
                    self.name, size / (1024 * 1024), nfiles
                ),
            )
            start_time = datetime.datetime.now()

        # Force all the files to download into the same directory.
        # Download in parallel
        import multiprocessing.dummy  # this uses threads

        download_logger = ArtifactDownloadLogger(nfiles=nfiles)

        def _download_file_with_thread_local_api_settings(
            name: str,
            root: str,
            download_logger: ArtifactDownloadLogger,
            tlas_api_key: Optional[str],
            tlas_cookies: Optional[Dict],
            tlas_headers: Optional[Dict],
        ) -> StrPath:
            _thread_local_api_settings.api_key = tlas_api_key
            _thread_local_api_settings.cookies = tlas_cookies
            _thread_local_api_settings.headers = tlas_headers

            return self._download_file(name, root, download_logger)

        pool = multiprocessing.dummy.Pool(32)
        pool.map(
            partial(
                _download_file_with_thread_local_api_settings,
                root=dirpath,
                download_logger=download_logger,
                tlas_api_key=_thread_local_api_settings.api_key,
                tlas_headers={**(_thread_local_api_settings.headers or {})},
                tlas_cookies={**(_thread_local_api_settings.cookies or {})},
            ),
            manifest.entries,
        )
        if recursive:
            pool.map(lambda artifact: artifact.download(), self._dependent_artifacts)
        pool.close()
        pool.join()

        self._is_downloaded = True

        if log:
            now = datetime.datetime.now()
            delta = abs((now - start_time).total_seconds())
            hours = int(delta // 3600)
            minutes = int((delta - hours * 3600) // 60)
            seconds = delta - hours * 3600 - minutes * 60
            termlog(
                f"Done. {hours}:{minutes}:{seconds:.1f}",
                prefix=False,
            )
        return FilePathStr(dirpath)

    def checkout(self, root: Optional[str] = None) -> str:
        dirpath = root or self._default_root(include_version=False)

        for root, _, files in os.walk(dirpath):
            for file in files:
                full_path = os.path.join(root, file)
                artifact_path = os.path.relpath(full_path, start=dirpath)
                try:
                    self.get_path(artifact_path)
                except KeyError:
                    # File is not part of the artifact, remove it.
                    os.remove(full_path)

        return self.download(root=dirpath)

    def verify(self, root: Optional[str] = None) -> None:
        dirpath = root or self._default_root()
        manifest = self._load_manifest()
        ref_count = 0

        for root, _, files in os.walk(dirpath):
            for file in files:
                full_path = os.path.join(root, file)
                artifact_path = os.path.relpath(full_path, start=dirpath)
                try:
                    self.get_path(artifact_path)
                except KeyError:
                    raise ValueError(
                        "Found file {} which is not a member of artifact {}".format(
                            full_path, self.name
                        )
                    )

        for entry in manifest.entries.values():
            if entry.ref is None:
                if md5_file_b64(os.path.join(dirpath, entry.path)) != entry.digest:
                    raise ValueError("Digest mismatch for file: %s" % entry.path)
            else:
                ref_count += 1
        if ref_count > 0:
            print("Warning: skipped verification of %s refs" % ref_count)

    def file(self, root: Optional[str] = None) -> StrPath:
        """Download a single file artifact to dir specified by the root.

        Arguments:
            root: (str, optional) The root directory in which to place the file. Defaults to './artifacts/self.name/'.

        Returns:
            (str): The full path of the downloaded file.
        """
        if root is None:
            root = os.path.join(".", "artifacts", self.name)

        manifest = self._load_manifest()
        nfiles = len(manifest.entries)
        if nfiles > 1:
            raise ValueError(
                "This artifact contains more than one file, call `.download()` to get all files or call "
                '.get_path("filename").download()'
            )

        return self._download_file(list(manifest.entries)[0], root=root)

    def _download_file(
        self,
        name: str,
        root: str,
        download_logger: Optional[ArtifactDownloadLogger] = None,
    ) -> StrPath:
        # download file into cache and copy to target dir
        downloaded_path = self.get_path(name).download(root)
        if download_logger is not None:
            download_logger.notify_downloaded()
        return downloaded_path

    def _default_root(self, include_version: bool = True) -> str:
        name = self.source_name if include_version else self.source_name.split(":")[0]
        root = os.path.join(get_artifact_dir(), name)
        if platform.system() == "Windows":
            head, tail = os.path.splitdrive(root)
            root = head + tail.replace(":", "-")
        return root

    def json_encode(self) -> Dict[str, Any]:
        return util.artifact_to_json(self)

    @normalize_exceptions
    def save(self) -> None:
        """Persists artifact changes to the wandb backend."""
        mutation = gql(
            """
        mutation updateArtifact(
            $artifactID: ID!,
            $description: String,
            $metadata: JSONString,
            $aliases: [ArtifactAliasInput!]
        ) {
            updateArtifact(input: {
                artifactID: $artifactID,
                description: $description,
                metadata: $metadata,
                aliases: $aliases
            }) {
                artifact {
                    id
                }
            }
        }
        """
        )
        introspect_query = gql(
            """
            query ProbeServerAddAliasesInput {
               AddAliasesInputInfoType: __type(name: "AddAliasesInput") {
                   name
                   inputFields {
                       name
                   }
                }
            }
            """
        )
        res = self.client.execute(introspect_query)
        valid = res.get("AddAliasesInputInfoType")
        aliases = None
        if not valid:
            # If valid, wandb backend version >= 0.13.0.
            # This means we can safely remove aliases from this updateArtifact request since we'll be calling
            # the alias endpoints below in _save_alias_changes.
            # If not valid, wandb backend version < 0.13.0. This requires aliases to be sent in updateArtifact.
            aliases = [
                {
                    "artifactCollectionName": self._artifact_collection_name,
                    "alias": alias,
                }
                for alias in self._aliases
            ]

        self.client.execute(
            mutation,
            variable_values={
                "artifactID": self.id,
                "description": self.description,
                "metadata": util.json_dumps_safer(self.metadata),
                "aliases": aliases,
            },
        )
        # Save locally modified aliases
        self._save_alias_changes()

    def wait(self) -> "Artifact":
        return self

    @normalize_exceptions
    def _save_alias_changes(self) -> None:
        """Persist alias changes on this artifact to the wandb backend.

        Called by artifact.save().
        """
        aliases_to_add = set(self._aliases) - set(self._frozen_aliases)
        aliases_to_remove = set(self._frozen_aliases) - set(self._aliases)

        # Introspect
        introspect_query = gql(
            """
            query ProbeServerAddAliasesInput {
               AddAliasesInputInfoType: __type(name: "AddAliasesInput") {
                   name
                   inputFields {
                       name
                   }
                }
            }
            """
        )
        res = self.client.execute(introspect_query)
        valid = res.get("AddAliasesInputInfoType")
        if not valid:
            return

        if len(aliases_to_add) > 0:
            add_mutation = gql(
                """
            mutation addAliases(
                $artifactID: ID!,
                $aliases: [ArtifactCollectionAliasInput!]!,
            ) {
                addAliases(
                    input: {
                        artifactID: $artifactID,
                        aliases: $aliases,
                    }
                ) {
                    success
                }
            }
            """
            )
            self.client.execute(
                add_mutation,
                variable_values={
                    "artifactID": self.id,
                    "aliases": [
                        {
                            "artifactCollectionName": self._artifact_collection_name,
                            "alias": alias,
                            "entityName": self._entity,
                            "projectName": self._project,
                        }
                        for alias in aliases_to_add
                    ],
                },
            )

        if len(aliases_to_remove) > 0:
            delete_mutation = gql(
                """
            mutation deleteAliases(
                $artifactID: ID!,
                $aliases: [ArtifactCollectionAliasInput!]!,
            ) {
                deleteAliases(
                    input: {
                        artifactID: $artifactID,
                        aliases: $aliases,
                    }
                ) {
                    success
                }
            }
            """
            )
            self.client.execute(
                delete_mutation,
                variable_values={
                    "artifactID": self.id,
                    "aliases": [
                        {
                            "artifactCollectionName": self._artifact_collection_name,
                            "alias": alias,
                            "entityName": self._entity,
                            "projectName": self._project,
                        }
                        for alias in aliases_to_remove
                    ],
                },
            )

        # reset local state
        self._frozen_aliases = self._aliases

    # TODO: not yet public, but we probably want something like this.
    def _list(self) -> Iterable[str]:
        manifest = self._load_manifest()
        return manifest.entries.keys()

    def __repr__(self) -> str:
        return f"<Artifact {self.id}>"

    def _load(self) -> Dict[str, Any]:
        query = gql(
            """
        query Artifact(
            $entityName: String,
            $projectName: String,
            $name: String!
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifact(name: $name) {
                    ...ArtifactFragment
                }
            }
        }
        %s
        """
            % ARTIFACT_FRAGMENT
        )
        response = None
        try:
            response = self.client.execute(
                query,
                variable_values={
                    "entityName": self.entity,
                    "projectName": self.project,
                    "name": self.name,
                },
            )
        except Exception:
            # we check for this after doing the call, since the backend supports raw digest lookups
            # which don't include ":" and are 32 characters long
            if ":" not in self.name and len(self.name) != 32:
                raise ValueError(
                    'Attempted to fetch artifact without alias (e.g. "<artifact_name>:v3" or "<artifact_name>:latest")'
                )
        if (
            response is None
            or response.get("project") is None
            or response["project"].get("artifact") is None
        ):
            raise ValueError(
                f'Project {self.entity}/{self.project} does not contain artifact: "{self.name}"'
            )
        return response["project"]["artifact"]

    def files(
        self, names: Optional[List[str]] = None, per_page: int = 50
    ) -> ArtifactFiles:
        """Iterate over all files stored in this artifact.

        Arguments:
            names: (list of str, optional) The filename paths relative to the
                root of the artifact you wish to list.
            per_page: (int, default 50) The number of files to return per request

        Returns:
            (`ArtifactFiles`): An iterator containing `File` objects
        """
        return ArtifactFiles(self.client, self, names, per_page)

    def _load_manifest(self) -> ArtifactManifest:
        if self._manifest is None:
            query = gql(
                """
            query ArtifactManifest(
                $entityName: String!,
                $projectName: String!,
                $name: String!
            ) {
                project(name: $projectName, entityName: $entityName) {
                    artifact(name: $name) {
                        currentManifest {
                            id
                            file {
                                id
                                directUrl
                            }
                        }
                    }
                }
            }
            """
            )
            response = self.client.execute(
                query,
                variable_values={
                    "entityName": self.entity,
                    "projectName": self.project,
                    "name": self.name,
                },
            )

            index_file_url = response["project"]["artifact"]["currentManifest"]["file"][
                "directUrl"
            ]
            with requests.get(index_file_url) as req:
                req.raise_for_status()
                self._manifest = ArtifactManifest.from_manifest_json(
                    json.loads(util.ensure_text(req.content))
                )

            self._load_dependent_manifests()

        return self._manifest

    def _load_dependent_manifests(self) -> None:
        """Interrogate entries and ensure we have loaded their manifests."""
        # Make sure dependencies are avail
        for entry_key in self.manifest.entries:
            entry = self.manifest.entries[entry_key]
            if self._manifest_entry_is_artifact_reference(entry):
                dep_artifact = self._get_ref_artifact_from_entry(entry)
                if dep_artifact not in self._dependent_artifacts:
                    dep_artifact._load_manifest()
                    self._dependent_artifacts.append(dep_artifact)

    @staticmethod
    def _manifest_entry_is_artifact_reference(entry: "ArtifactManifestEntry") -> bool:
        """Determine if an ArtifactManifestEntry is an artifact reference."""
        return (
            entry.ref is not None
            and urllib.parse.urlparse(entry.ref).scheme == "wandb-artifact"
        )

    def _get_ref_artifact_from_entry(
        self, entry: "ArtifactManifestEntry"
    ) -> "Artifact":
        """Helper function returns the referenced artifact from an entry."""
        artifact_id = util.host_from_path(entry.ref)
        artifact = Artifact.from_id(hex_to_b64_id(artifact_id), self.client)
        assert artifact is not None
        return artifact

    def used_by(self) -> List[Run]:
        """Retrieve the runs which use this artifact directly.

        Returns:
            [Run]: a list of Run objects which use this artifact
        """
        query = gql(
            """
            query ArtifactUsedBy(
                $id: ID!,
                $before: String,
                $after: String,
                $first: Int,
                $last: Int
            ) {
                artifact(id: $id) {
                    usedBy(before: $before, after: $after, first: $first, last: $last) {
                        edges {
                            node {
                                name
                                project {
                                    name
                                    entityName
                                }
                            }
                        }
                    }
                }
            }
        """
        )
        response = self.client.execute(
            query,
            variable_values={"id": self.id},
        )
        # yes, "name" is actually id
        runs = [
            Run(
                self.client,
                edge["node"]["project"]["entityName"],
                edge["node"]["project"]["name"],
                edge["node"]["name"],
            )
            for edge in response.get("artifact", {}).get("usedBy", {}).get("edges", [])
        ]
        return runs

    def logged_by(self) -> Optional[Run]:
        """Retrieve the run which logged this artifact.

        Returns:
            Run: Run object which logged this artifact
        """
        query = gql(
            """
            query ArtifactCreatedBy(
                $id: ID!
            ) {
                artifact(id: $id) {
                    createdBy {
                        ... on Run {
                            name
                            project {
                                name
                                entityName
                            }
                        }
                    }
                }
            }
        """
        )
        response = self.client.execute(
            query,
            variable_values={"id": self.id},
        )
        run_obj = response.get("artifact", {}).get("createdBy", {})
        if run_obj is None:
            return None
        return Run(
            self.client,
            run_obj["project"]["entityName"],
            run_obj["project"]["name"],
            run_obj["name"],
        )

    def new_draft(self) -> "LocalArtifact":
        """Create a new draft artifact with the same content as this committed artifact.

        The artifact returned can be extended or modified and logged as a new version.
        """
        artifact = wandb.Artifact(self.name.split(":")[0], self.type)
        artifact._description = self.description
        artifact._metadata = self.metadata
        artifact._manifest = ArtifactManifest.from_manifest_json(
            self.manifest.to_manifest_json()
        )
        return artifact
