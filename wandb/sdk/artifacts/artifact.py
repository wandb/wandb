"""Artifact class."""
import concurrent.futures
import contextlib
import json
import multiprocessing.dummy
import os
import re
import shutil
import tempfile
import time
from copy import copy
from datetime import datetime, timedelta
from functools import partial
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
    Set,
    Tuple,
    Type,
    Union,
    cast,
)
from urllib.parse import urlparse

import requests

import wandb
from wandb import data_types, env, util
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public import ArtifactCollection, ArtifactFiles, RetryingClient, Run
from wandb.data_types import WBValue
from wandb.errors.term import termerror, termlog, termwarn
from wandb.sdk.artifacts.artifact_cache import artifact_cache
from wandb.sdk.artifacts.artifact_download_logger import ArtifactDownloadLogger
from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifact_manifests.artifact_manifest_v1 import (
    ArtifactManifestV1,
)
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.artifacts.artifact_ttl import ArtifactTTL
from wandb.sdk.artifacts.exceptions import (
    ArtifactFinalizedError,
    ArtifactNotLoggedError,
    WaitTimeoutError,
)
from wandb.sdk.artifacts.staging import get_staging_dir
from wandb.sdk.artifacts.storage_layout import StorageLayout
from wandb.sdk.artifacts.storage_policies import WANDB_STORAGE_POLICY
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.data_types._dtypes import Type as WBType
from wandb.sdk.data_types._dtypes import TypeRegistry
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.lib import filesystem, retry, runid, telemetry
from wandb.sdk.lib.hashutil import B64MD5, b64_to_hex_id, md5_file_b64
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr

reset_path = util.vendor_setup()

from wandb_gql import gql  # noqa: E402

reset_path()

if TYPE_CHECKING:
    from wandb.sdk.interface.message_future import MessageFuture


class Artifact:
    """Flexible and lightweight building block for dataset and model versioning.

    Constructs an empty artifact whose contents can be populated using its `add` family
    of functions. Once the artifact has all the desired files, you can call
    `wandb.log_artifact()` to log it.

    Arguments:
        name: A human-readable name for this artifact, which is how you can identify
            this artifact in the UI or reference it in `use_artifact` calls. Names can
            contain letters, numbers, underscores, hyphens, and dots. The name must be
            unique across a project.
        type: The type of the artifact, which is used to organize and differentiate
            artifacts. Common types include `dataset` or `model`, but you can use any
            string containing letters, numbers, underscores, hyphens, and dots.
        description: Free text that offers a description of the artifact. The
            description is markdown rendered in the UI, so this is a good place to place
            tables, links, etc.
        metadata: Structured data associated with the artifact, for example class
            distribution of a dataset. This will eventually be queryable and plottable
            in the UI. There is a hard limit of 100 total keys.

    Returns:
        An `Artifact` object.

    Examples:
        Basic usage:
        ```python
        wandb.init()

        artifact = wandb.Artifact("mnist", type="dataset")
        artifact.add_dir("mnist/")
        wandb.log_artifact(artifact)
        ```
    """

    _TMP_DIR = tempfile.TemporaryDirectory("wandb-artifacts")

    def __init__(
        self,
        name: str,
        type: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        incremental: bool = False,
        use_as: Optional[str] = None,
    ) -> None:
        if not re.match(r"^[a-zA-Z0-9_\-.]+$", name):
            raise ValueError(
                f"Artifact name may only contain alphanumeric characters, dashes, "
                f"underscores, and dots. Invalid name: {name}"
            )
        if type == "job" or type.startswith("wandb-"):
            raise ValueError(
                "Artifact types 'job' and 'wandb-*' are reserved for internal use. "
                "Please use a different type."
            )
        if incremental:
            termwarn("Using experimental arg `incremental`")

        # Internal.
        self._client: Optional[RetryingClient] = None

        storage_policy_cls = StoragePolicy.lookup_by_name(WANDB_STORAGE_POLICY)
        layout = StorageLayout.V1 if env.get_use_v1_artifacts() else StorageLayout.V2
        policy_config = {"storageLayout": layout}
        self._storage_policy = storage_policy_cls.from_config(config=policy_config)

        self._tmp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._added_objs: Dict[
            int, Tuple[data_types.WBValue, ArtifactManifestEntry]
        ] = {}
        self._added_local_paths: Dict[str, ArtifactManifestEntry] = {}
        self._save_future: Optional[MessageFuture] = None
        self._dependent_artifacts: Set[Artifact] = set()
        self._download_roots: Set[str] = set()
        # Set by new_draft(), otherwise the latest artifact will be used as the base.
        self._base_id: Optional[str] = None
        # Properties.
        self._id: Optional[str] = None
        self._client_id: str = runid.generate_id(128)
        self._sequence_client_id: str = runid.generate_id(128)
        self._entity: Optional[str] = None
        self._project: Optional[str] = None
        self._name: str = name  # includes version after saving
        self._version: Optional[str] = None
        self._source_entity: Optional[str] = None
        self._source_project: Optional[str] = None
        self._source_name: str = name  # includes version after saving
        self._source_version: Optional[str] = None
        self._type: str = type
        self._description: Optional[str] = description
        self._metadata: dict = self._normalize_metadata(metadata)
        self._ttl_duration_seconds: Optional[int] = None
        self._ttl_is_inherited: bool = True
        self._ttl_changed: bool = False
        self._aliases: List[str] = []
        self._saved_aliases: List[str] = []
        self._distributed_id: Optional[str] = None
        self._incremental: bool = incremental
        self._use_as: Optional[str] = use_as
        self._state: ArtifactState = ArtifactState.PENDING
        self._manifest: Optional[ArtifactManifest] = ArtifactManifestV1(
            self._storage_policy
        )
        self._commit_hash: Optional[str] = None
        self._file_count: Optional[int] = None
        self._created_at: Optional[str] = None
        self._updated_at: Optional[str] = None
        self._final: bool = False

        # Cache.
        artifact_cache[self._client_id] = self

    def __repr__(self) -> str:
        return f"<Artifact {self.id or self.name}>"

    @classmethod
    def _from_id(cls, artifact_id: str, client: RetryingClient) -> Optional["Artifact"]:
        artifact = artifact_cache.get(artifact_id)
        if artifact is not None:
            return artifact

        query = gql(
            """
            query ArtifactByID($id: ID!) {
                artifact(id: $id) {
                    ...ArtifactFragment
                    currentManifest {
                        file {
                            directUrl
                        }
                    }
                }
            }
            """
            + cls._get_gql_artifact_fragment()
        )
        response = client.execute(
            query,
            variable_values={"id": artifact_id},
        )
        attrs = response.get("artifact")
        if attrs is None:
            return None
        entity = attrs["artifactSequence"]["project"]["entityName"]
        project = attrs["artifactSequence"]["project"]["name"]
        name = "{}:v{}".format(attrs["artifactSequence"]["name"], attrs["versionIndex"])
        return cls._from_attrs(entity, project, name, attrs, client)

    @classmethod
    def _from_name(
        cls, entity: str, project: str, name: str, client: RetryingClient
    ) -> "Artifact":
        query = gql(
            """
            query ArtifactByName(
                $entityName: String!,
                $projectName: String!,
                $name: String!
            ) {
                project(name: $projectName, entityName: $entityName) {
                    artifact(name: $name) {
                        ...ArtifactFragment
                    }
                }
            }
            """
            + cls._get_gql_artifact_fragment()
        )
        response = client.execute(
            query,
            variable_values={
                "entityName": entity,
                "projectName": project,
                "name": name,
            },
        )
        attrs = response.get("project", {}).get("artifact")
        if attrs is None:
            raise ValueError(
                f"Unable to fetch artifact with name {entity}/{project}/{name}"
            )
        return cls._from_attrs(entity, project, name, attrs, client)

    @classmethod
    def _from_attrs(
        cls,
        entity: str,
        project: str,
        name: str,
        attrs: Dict[str, Any],
        client: RetryingClient,
    ) -> "Artifact":
        # Placeholder is required to skip validation.
        artifact = cls("placeholder", type="placeholder")
        artifact._client = client
        artifact._id = attrs["id"]
        artifact._entity = entity
        artifact._project = project
        artifact._name = name
        aliases = [
            alias["alias"]
            for alias in attrs["aliases"]
            if alias["artifactCollection"]["project"]["entityName"] == entity
            and alias["artifactCollection"]["project"]["name"] == project
            and alias["artifactCollection"]["name"] == name.split(":")[0]
        ]
        version_aliases = [
            alias for alias in aliases if util.alias_is_version_index(alias)
        ]
        assert len(version_aliases) == 1
        artifact._version = version_aliases[0]
        artifact._source_entity = attrs["artifactSequence"]["project"]["entityName"]
        artifact._source_project = attrs["artifactSequence"]["project"]["name"]
        artifact._source_name = "{}:v{}".format(
            attrs["artifactSequence"]["name"], attrs["versionIndex"]
        )
        artifact._source_version = "v{}".format(attrs["versionIndex"])
        artifact._type = attrs["artifactType"]["name"]
        artifact._description = attrs["description"]
        artifact.metadata = cls._normalize_metadata(
            json.loads(attrs["metadata"] or "{}")
        )
        artifact._ttl_duration_seconds = artifact._ttl_duration_seconds_from_gql(
            attrs.get("ttlDurationSeconds")
        )
        artifact._ttl_is_inherited = (
            True if attrs.get("ttlIsInherited") is None else attrs["ttlIsInherited"]
        )
        artifact._aliases = [
            alias for alias in aliases if not util.alias_is_version_index(alias)
        ]
        artifact._saved_aliases = copy(artifact._aliases)
        artifact._state = ArtifactState(attrs["state"])
        if "currentManifest" in attrs:
            artifact._load_manifest(attrs["currentManifest"]["file"]["directUrl"])
        else:
            artifact._manifest = None
        artifact._commit_hash = attrs["commitHash"]
        artifact._file_count = attrs["fileCount"]
        artifact._created_at = attrs["createdAt"]
        artifact._updated_at = attrs["updatedAt"]
        artifact._final = True
        # Cache.

        assert artifact.id is not None
        artifact_cache[artifact.id] = artifact
        return artifact

    def new_draft(self) -> "Artifact":
        """Create a new draft artifact with the same content as this committed artifact.

        The artifact returned can be extended or modified and logged as a new version.

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
        """
        self._ensure_logged("new_draft")

        # Name, _entity and _project are set to the *source* name/entity/project:
        # if this artifact is saved it must be saved to the source sequence.
        artifact = Artifact(self.source_name.split(":")[0], self.type)
        artifact._entity = self._source_entity
        artifact._project = self._source_project
        artifact._source_entity = self._source_entity
        artifact._source_project = self._source_project

        # This artifact's parent is the one we are making a draft from.
        artifact._base_id = self.id

        # We can reuse the client, and copy over all the attributes that aren't
        # version-dependent and don't depend on having been logged.
        artifact._client = self._client
        artifact._description = self.description
        artifact._metadata = self.metadata
        artifact._manifest = ArtifactManifest.from_manifest_json(
            self.manifest.to_manifest_json()
        )
        return artifact

    # Properties.

    @property
    def id(self) -> Optional[str]:
        """The artifact's ID."""
        if self.is_draft():
            return None
        assert self._id is not None
        return self._id

    @property
    def entity(self) -> str:
        """The name of the entity of the secondary (portfolio) artifact collection."""
        self._ensure_logged("entity")
        assert self._entity is not None
        return self._entity

    @property
    def project(self) -> str:
        """The name of the project of the secondary (portfolio) artifact collection."""
        self._ensure_logged("project")
        assert self._project is not None
        return self._project

    @property
    def name(self) -> str:
        """The artifact name and version in its secondary (portfolio) collection.

        A string with the format {collection}:{alias}. Before the artifact is saved,
        contains only the name since the version is not yet known.
        """
        return self._name

    @property
    def qualified_name(self) -> str:
        """The entity/project/name of the secondary (portfolio) collection."""
        return f"{self.entity}/{self.project}/{self.name}"

    @property
    def version(self) -> str:
        """The artifact's version in its secondary (portfolio) collection."""
        self._ensure_logged("version")
        assert self._version is not None
        return self._version

    @property
    def collection(self) -> ArtifactCollection:
        """The collection this artifact was retrieved from.

        If this artifact was retrieved from a portfolio / linked collection, that
        collection will be returned rather than the source sequence.
        """
        self._ensure_logged("collection")
        base_name = self.name.split(":")[0]
        return ArtifactCollection(
            self._client, self.entity, self.project, base_name, self.type
        )

    @property
    def source_entity(self) -> str:
        """The name of the entity of the primary (sequence) artifact collection."""
        self._ensure_logged("source_entity")
        assert self._source_entity is not None
        return self._source_entity

    @property
    def source_project(self) -> str:
        """The name of the project of the primary (sequence) artifact collection."""
        self._ensure_logged("source_project")
        assert self._source_project is not None
        return self._source_project

    @property
    def source_name(self) -> str:
        """The artifact name and version in its primary (sequence) collection.

        A string with the format {collection}:{alias}. Before the artifact is saved,
        contains only the name since the version is not yet known.
        """
        return self._source_name

    @property
    def source_qualified_name(self) -> str:
        """The entity/project/name of the primary (sequence) collection."""
        return f"{self.source_entity}/{self.source_project}/{self.source_name}"

    @property
    def source_version(self) -> str:
        """The artifact's version in its primary (sequence) collection.

        A string with the format "v{number}".
        """
        self._ensure_logged("source_version")
        assert self._source_version is not None
        return self._source_version

    @property
    def source_collection(self) -> ArtifactCollection:
        """The artifact's primary (sequence) collection."""
        self._ensure_logged("source_collection")
        base_name = self.source_name.split(":")[0]
        return ArtifactCollection(
            self._client, self.source_entity, self.source_project, base_name, self.type
        )

    @property
    def type(self) -> str:
        """The artifact's type."""
        return self._type

    @property
    def description(self) -> Optional[str]:
        """The artifact description.

        Free text that offers a user-set description of the artifact.
        """
        return self._description

    @description.setter
    def description(self, description: Optional[str]) -> None:
        """Set the description of the artifact.

        The description is markdown rendered in the UI, so this is a good place to put
        links, etc.

        Arguments:
            desc: Free text that offers a description of the artifact.
        """
        self._description = description

    @property
    def metadata(self) -> dict:
        """User-defined artifact metadata.

        Structured data associated with the artifact.
        """
        return self._metadata

    @metadata.setter
    def metadata(self, metadata: dict) -> None:
        """User-defined artifact metadata.

        Metadata set this way will eventually be queryable and plottable in the UI; e.g.
        the class distribution of a dataset.

        Note: There is currently a limit of 100 total keys.

        Arguments:
            metadata: Structured data associated with the artifact.
        """
        self._metadata = self._normalize_metadata(metadata)

    @property
    def ttl(self) -> Union[timedelta, None]:
        """Time To Live (TTL).

        The artifact will be deleted shortly after TTL since its creation.
        None means the artifact will never expire.
        If TTL is not set on an artifact, it will inherit the default for its collection.

        Raises:
            ArtifactNotLoggedError: Unable to fetch inherited TTL if the artifact has not been logged or saved
        """
        if self._ttl_is_inherited and (self.is_draft() or self._ttl_changed):
            raise ArtifactNotLoggedError(self, "ttl")
        if self._ttl_duration_seconds is None:
            return None
        return timedelta(seconds=self._ttl_duration_seconds)

    @ttl.setter
    def ttl(self, ttl: Union[timedelta, ArtifactTTL, None]) -> None:
        """Time To Live (TTL).

        The artifact will be deleted shortly after TTL since its creation. None means the artifact will never expire.
        If TTL is not set on an artifact, it will inherit the default TTL rules for its collection.

        Arguments:
            ttl: How long the artifact will remain active from its creation.
                - Timedelta must be positive.
                - `None` means the artifact will never expire.
                - wandb.ArtifactTTL.INHERIT will set the TTL to go back to the default and inherit from collection rules.
        """
        if self.type == "wandb-history":
            raise ValueError("Cannot set artifact TTL for type wandb-history")

        self._ttl_changed = True
        if isinstance(ttl, ArtifactTTL):
            if ttl == ArtifactTTL.INHERIT:
                self._ttl_is_inherited = True
            else:
                raise ValueError(f"Unhandled ArtifactTTL enum {ttl}")
        else:
            self._ttl_is_inherited = False
            if ttl is None:
                self._ttl_duration_seconds = None
            else:
                if ttl.total_seconds() <= 0:
                    raise ValueError(
                        f"Artifact TTL Duration has to be positive. ttl: {ttl.total_seconds()}"
                    )
                self._ttl_duration_seconds = int(ttl.total_seconds())

    @property
    def aliases(self) -> List[str]:
        """The aliases associated with this artifact.

        The list is mutable and calling `save()` will persist all alias changes.
        """
        self._ensure_logged("aliases")
        return self._aliases

    @aliases.setter
    def aliases(self, aliases: List[str]) -> None:
        """Set the aliases associated with this artifact."""
        self._ensure_logged("aliases")

        if any(char in alias for alias in aliases for char in ["/", ":"]):
            raise ValueError(
                "Aliases must not contain any of the following characters: /, :"
            )
        self._aliases = aliases

    @property
    def distributed_id(self) -> Optional[str]:
        return self._distributed_id

    @distributed_id.setter
    def distributed_id(self, distributed_id: Optional[str]) -> None:
        self._distributed_id = distributed_id

    @property
    def incremental(self) -> bool:
        return self._incremental

    @property
    def use_as(self) -> Optional[str]:
        return self._use_as

    @property
    def state(self) -> str:
        """The status of the artifact. One of: "PENDING", "COMMITTED", or "DELETED"."""
        return self._state.value

    @property
    def manifest(self) -> ArtifactManifest:
        """The artifact's manifest.

        The manifest lists all of its contents, and can't be changed once the artifact
        has been logged.
        """
        if self._manifest is None:
            query = gql(
                """
                query ArtifactManifest(
                    $entityName: String!,
                    $projectName: String!,
                    $name: String!
                ) {
                    project(entityName: $entityName, name: $projectName) {
                        artifact(name: $name) {
                            currentManifest {
                                file {
                                    directUrl
                                }
                            }
                        }
                    }
                }
                """
            )
            assert self._client is not None
            response = self._client.execute(
                query,
                variable_values={
                    "entityName": self._entity,
                    "projectName": self._project,
                    "name": self._name,
                },
            )
            attrs = response["project"]["artifact"]
            self._load_manifest(attrs["currentManifest"]["file"]["directUrl"])
            assert self._manifest is not None
        return self._manifest

    @property
    def digest(self) -> str:
        """The logical digest of the artifact.

        The digest is the checksum of the artifact's contents. If an artifact has the
        same digest as the current `latest` version, then `log_artifact` is a no-op.
        """
        return self.manifest.digest()

    @property
    def size(self) -> int:
        """The total size of the artifact in bytes.

        Includes any references tracked by this artifact.
        """
        total_size: int = 0
        for entry in self.manifest.entries.values():
            if entry.size is not None:
                total_size += entry.size
        return total_size

    @property
    def commit_hash(self) -> str:
        """The hash returned when this artifact was committed."""
        self._ensure_logged("commit_hash")
        assert self._commit_hash is not None
        return self._commit_hash

    @property
    def file_count(self) -> int:
        """The number of files (including references)."""
        self._ensure_logged("file_count")
        assert self._file_count is not None
        return self._file_count

    @property
    def created_at(self) -> str:
        """The time at which the artifact was created."""
        self._ensure_logged("created_at")
        assert self._created_at is not None
        return self._created_at

    @property
    def updated_at(self) -> str:
        """The time at which the artifact was last updated."""
        self._ensure_logged("updated_at")
        assert self._created_at is not None
        return self._updated_at or self._created_at

    # State management.

    def finalize(self) -> None:
        """Mark this artifact as final, disallowing further modifications.

        This happens automatically when calling `log_artifact`.
        """
        self._final = True

    def _ensure_can_add(self) -> None:
        if self._final:
            raise ArtifactFinalizedError(artifact=self)

    def _ensure_logged(self, attr: Optional[str] = None) -> None:
        if self.is_draft():
            raise ArtifactNotLoggedError(self, attr)

    def is_draft(self) -> bool:
        """Whether the artifact is a draft, i.e. it hasn't been saved yet."""
        return self._state == ArtifactState.PENDING

    def _is_draft_save_started(self) -> bool:
        return self._save_future is not None

    def save(
        self,
        project: Optional[str] = None,
        settings: Optional["wandb.wandb_sdk.wandb_settings.Settings"] = None,
    ) -> None:
        """Persist any changes made to the artifact.

        If currently in a run, that run will log this artifact. If not currently in a
        run, a run of type "auto" will be created to track this artifact.

        Arguments:
            project: A project to use for the artifact in the case that a run is not
                already in context
            settings: A settings object to use when initializing an automatic run. Most
                commonly used in testing harness.
        """
        if self._state != ArtifactState.PENDING:
            return self._update()

        if self._incremental:
            with telemetry.context() as tel:
                tel.feature.artifact_incremental = True

        if wandb.run is None:
            if settings is None:
                settings = wandb.Settings(silent="true")
            with wandb.init(
                entity=self._source_entity,
                project=project or self._source_project,
                job_type="auto",
                settings=settings,
            ) as run:
                # redoing this here because in this branch we know we didn't
                # have the run at the beginning of the method
                if self._incremental:
                    with telemetry.context(run=run) as tel:
                        tel.feature.artifact_incremental = True
                run.log_artifact(self)
        else:
            wandb.run.log_artifact(self)

    def _set_save_future(
        self, save_future: "MessageFuture", client: RetryingClient
    ) -> None:
        self._save_future = save_future
        self._client = client

    def wait(self, timeout: Optional[int] = None) -> "Artifact":
        """Wait for this artifact to finish logging, if needed.

        Arguments:
            timeout: Wait up to this long.
        """
        if self.is_draft():
            if self._save_future is None:
                raise ArtifactNotLoggedError(self, "wait")
            result = self._save_future.get(timeout)
            if not result:
                raise WaitTimeoutError(
                    "Artifact upload wait timed out, failed to fetch Artifact response"
                )
            response = result.response.log_artifact_response
            if response.error_message:
                raise ValueError(response.error_message)
            self._populate_after_save(response.artifact_id)
        return self

    def _populate_after_save(self, artifact_id: str) -> None:
        query_template = """
            query ArtifactByIDShort($id: ID!) {
                artifact(id: $id) {
                    artifactSequence {
                        project {
                            entityName
                            name
                        }
                        name
                    }
                    versionIndex
                    ttlDurationSeconds
                    ttlIsInherited
                    aliases {
                        artifactCollection {
                            project {
                                entityName
                                name
                            }
                            name
                        }
                        alias
                    }
                    state
                    currentManifest {
                        file {
                            directUrl
                        }
                    }
                    commitHash
                    fileCount
                    createdAt
                    updatedAt
                }
            }
        """

        fields = InternalApi().server_artifact_introspection()
        if "ttlIsInherited" not in fields:
            query_template = query_template.replace("ttlDurationSeconds", "").replace(
                "ttlIsInherited",
                "",
            )
        query = gql(query_template)

        assert self._client is not None
        response = self._client.execute(
            query,
            variable_values={"id": artifact_id},
        )
        attrs = response.get("artifact")
        if attrs is None:
            raise ValueError(f"Unable to fetch artifact with id {artifact_id}")
        self._id = artifact_id
        self._entity = attrs["artifactSequence"]["project"]["entityName"]
        self._project = attrs["artifactSequence"]["project"]["name"]
        self._name = "{}:v{}".format(
            attrs["artifactSequence"]["name"], attrs["versionIndex"]
        )
        self._version = "v{}".format(attrs["versionIndex"])
        self._source_entity = self._entity
        self._source_project = self._project
        self._source_name = self._name
        self._source_version = self._version
        self._ttl_duration_seconds = self._ttl_duration_seconds_from_gql(
            attrs.get("ttlDurationSeconds")
        )
        self._ttl_is_inherited = (
            True if attrs.get("ttlIsInherited") is None else attrs["ttlIsInherited"]
        )
        self._ttl_changed = False  # Reset after saving artifact
        self._aliases = [
            alias["alias"]
            for alias in attrs["aliases"]
            if alias["artifactCollection"]["project"]["entityName"] == self._entity
            and alias["artifactCollection"]["project"]["name"] == self._project
            and alias["artifactCollection"]["name"] == self._name.split(":")[0]
            and not util.alias_is_version_index(alias["alias"])
        ]
        self._state = ArtifactState(attrs["state"])
        self._load_manifest(attrs["currentManifest"]["file"]["directUrl"])
        self._commit_hash = attrs["commitHash"]
        self._file_count = attrs["fileCount"]
        self._created_at = attrs["createdAt"]
        self._updated_at = attrs["updatedAt"]

    @normalize_exceptions
    def _update(self) -> None:
        """Persists artifact changes to the wandb backend."""
        aliases = None
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
        assert self._client is not None
        response = self._client.execute(introspect_query)
        if response.get("AddAliasesInputInfoType"):  # wandb backend version >= 0.13.0
            aliases_to_add = set(self._aliases) - set(self._saved_aliases)
            aliases_to_delete = set(self._saved_aliases) - set(self._aliases)
            if len(aliases_to_add) > 0:
                add_mutation = gql(
                    """
                    mutation addAliases(
                        $artifactID: ID!,
                        $aliases: [ArtifactCollectionAliasInput!]!,
                    ) {
                        addAliases(
                            input: {artifactID: $artifactID, aliases: $aliases}
                        ) {
                            success
                        }
                    }
                    """
                )
                assert self._client is not None
                self._client.execute(
                    add_mutation,
                    variable_values={
                        "artifactID": self.id,
                        "aliases": [
                            {
                                "entityName": self._entity,
                                "projectName": self._project,
                                "artifactCollectionName": self._name.split(":")[0],
                                "alias": alias,
                            }
                            for alias in aliases_to_add
                        ],
                    },
                )
            if len(aliases_to_delete) > 0:
                delete_mutation = gql(
                    """
                    mutation deleteAliases(
                        $artifactID: ID!,
                        $aliases: [ArtifactCollectionAliasInput!]!,
                    ) {
                        deleteAliases(
                            input: {artifactID: $artifactID, aliases: $aliases}
                        ) {
                            success
                        }
                    }
                    """
                )
                assert self._client is not None
                self._client.execute(
                    delete_mutation,
                    variable_values={
                        "artifactID": self.id,
                        "aliases": [
                            {
                                "entityName": self._entity,
                                "projectName": self._project,
                                "artifactCollectionName": self._name.split(":")[0],
                                "alias": alias,
                            }
                            for alias in aliases_to_delete
                        ],
                    },
                )
            self._saved_aliases = copy(self._aliases)
        else:  # wandb backend version < 0.13.0
            aliases = [
                {
                    "artifactCollectionName": self._name.split(":")[0],
                    "alias": alias,
                }
                for alias in self._aliases
            ]

        mutation_template = """
            mutation updateArtifact(
                $artifactID: ID!,
                $description: String,
                $metadata: JSONString,
                _TTL_DURATION_SECONDS_TYPE_
                $aliases: [ArtifactAliasInput!]
            ) {
                updateArtifact(
                    input: {
                        artifactID: $artifactID,
                        description: $description,
                        metadata: $metadata,
                        _TTL_DURATION_SECONDS_VALUE_
                        aliases: $aliases
                    }
                ) {
                    artifact {
                        id
                        _TTL_DURATION_SECONDS_FIELDS_
                    }
                }
            }
        """
        fields = InternalApi().server_artifact_introspection()
        if "ttlIsInherited" in fields:
            mutation_template = (
                mutation_template.replace(
                    "_TTL_DURATION_SECONDS_TYPE_", "$ttlDurationSeconds: Int64,"
                )
                .replace(
                    "_TTL_DURATION_SECONDS_VALUE_",
                    "ttlDurationSeconds: $ttlDurationSeconds,",
                )
                .replace(
                    "_TTL_DURATION_SECONDS_FIELDS_", "ttlDurationSeconds ttlIsInherited"
                )
            )
        else:
            if self._ttl_changed:
                termwarn(
                    "Server not compatible with setting Artifact TTLs, please upgrade the server to use Artifact TTL"
                )
            mutation_template = (
                mutation_template.replace("_TTL_DURATION_SECONDS_TYPE_", "")
                .replace(
                    "_TTL_DURATION_SECONDS_VALUE_",
                    "",
                )
                .replace("_TTL_DURATION_SECONDS_FIELDS_", "")
            )
        mutation = gql(mutation_template)
        assert self._client is not None

        ttl_duration_input = self._ttl_duration_seconds_to_gql()
        response = self._client.execute(
            mutation,
            variable_values={
                "artifactID": self.id,
                "description": self.description,
                "metadata": util.json_dumps_safer(self.metadata),
                "ttlDurationSeconds": ttl_duration_input,
                "aliases": aliases,
            },
        )
        attrs = response["updateArtifact"]["artifact"]

        # Update ttl_duration_seconds based on updateArtifact
        self._ttl_duration_seconds = self._ttl_duration_seconds_from_gql(
            attrs.get("ttlDurationSeconds")
        )
        self._ttl_is_inherited = (
            True if attrs.get("ttlIsInherited") is None else attrs["ttlIsInherited"]
        )
        self._ttl_changed = False  # Reset after updating artifact

    # Adding, removing, getting entries.

    def __getitem__(self, name: str) -> Optional[data_types.WBValue]:
        """Get the WBValue object located at the artifact relative `name`.

        Arguments:
            name: The artifact relative name to get

        Raises:
            ArtifactNotLoggedError: if the artifact isn't logged or the run is offline

        Examples:
            Basic usage:
            ```python
            artifact = wandb.Artifact("my_table", type="dataset")
            table = wandb.Table(
                columns=["a", "b", "c"], data=[(i, i * 2, 2**i) for i in range(10)]
            )
            artifact["my_table"] = table

            wandb.log_artifact(artifact)
            ```

            Retrieving an object:
            ```python
            artifact = wandb.use_artifact("my_table:latest")
            table = artifact["my_table"]
            ```
        """
        return self.get(name)

    def __setitem__(self, name: str, item: data_types.WBValue) -> ArtifactManifestEntry:
        """Add `item` to the artifact at path `name`.

        Arguments:
            name: The path within the artifact to add the object.
            item: The object to add.

        Returns:
            The added manifest entry

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.

        Examples:
            Basic usage:
            ```python
            artifact = wandb.Artifact("my_table", type="dataset")
            table = wandb.Table(
                columns=["a", "b", "c"], data=[(i, i * 2, 2**i) for i in range(10)]
            )
            artifact["my_table"] = table

            wandb.log_artifact(artifact)
            ```

            Retrieving an object:
            ```python
            artifact = wandb.use_artifact("my_table:latest")
            table = artifact["my_table"]
            ```
        """
        return self.add(item, name)

    @contextlib.contextmanager
    def new_file(
        self, name: str, mode: str = "w", encoding: Optional[str] = None
    ) -> Generator[IO, None, None]:
        """Open a new temporary file that will be automatically added to the artifact.

        Arguments:
            name: The name of the new file being added to the artifact.
            mode: The mode in which to open the new file.
            encoding: The encoding in which to open the new file.

        Returns:
            A new file object that can be written to. Upon closing, the file will be
            automatically added to the artifact.

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.

        Examples:
            ```python
            artifact = wandb.Artifact("my_data", type="dataset")
            with artifact.new_file("hello.txt") as f:
                f.write("hello!")
            wandb.log_artifact(artifact)
            ```
        """
        self._ensure_can_add()
        if self._tmp_dir is None:
            self._tmp_dir = tempfile.TemporaryDirectory()
        path = os.path.join(self._tmp_dir.name, name.lstrip("/"))
        if os.path.exists(path):
            raise ValueError(f"File with name {name!r} already exists at {path!r}")

        filesystem.mkdir_exists_ok(os.path.dirname(path))
        try:
            with util.fsync_open(path, mode, encoding) as f:
                yield f
        except UnicodeEncodeError as e:
            termerror(
                f"Failed to open the provided file (UnicodeEncodeError: {e}). Please "
                f"provide the proper encoding."
            )
            raise e

        self.add_file(path, name=name)

    def add_file(
        self,
        local_path: str,
        name: Optional[str] = None,
        is_tmp: Optional[bool] = False,
    ) -> ArtifactManifestEntry:
        """Add a local file to the artifact.

        Arguments:
            local_path: The path to the file being added.
            name: The path within the artifact to use for the file being added. Defaults
                to the basename of the file.
            is_tmp: If true, then the file is renamed deterministically to avoid
                collisions.

        Returns:
            The added manifest entry

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized

        Examples:
            Add a file without an explicit name:
            ```python
            # Add as `file.txt'
            artifact.add_file("path/to/file.txt")
            ```

            Add a file with an explicit name:
            ```python
            # Add as 'new/path/file.txt'
            artifact.add_file("path/to/file.txt", name="new/path/file.txt")
            ```
        """
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
        """Add a local directory to the artifact.

        Arguments:
            local_path: The path to the directory being added.
            name: The path within the artifact to use for the directory being added.
                Defaults to the root of the artifact.

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized

        Examples:
            Add a directory without an explicit name:
            ```python
            # All files in `my_dir/` are added at the root of the artifact.
            artifact.add_dir("my_dir/")
            ```

            Add a directory and name it explicitly:
            ```python
            # All files in `my_dir/` are added under `destination/`.
            artifact.add_dir("my_dir/", name="destination")
            ```
        """
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
        - https, domain matching *.blob.core.windows.net (Azure): The checksum and size
          will be pulled from the blob metadata. If storage account versioning is
          enabled, then the version ID is also tracked.
        - file: The checksum and size will be pulled from the file system. This scheme
          is useful if you have an NFS share or other externally mounted volume
          containing files you wish to track but not necessarily upload.

        For any other scheme, the digest is just a hash of the URI and the size is left
        blank.

        Arguments:
            uri: The URI path of the reference to add. Can be an object returned from
                Artifact.get_path to store a reference to another artifact's entry.
            name: The path within the artifact to place the contents of this reference
            checksum: Whether or not to checksum the resource(s) located at the
                reference URI. Checksumming is strongly recommended as it enables
                automatic integrity validation, however it can be disabled to speed up
                artifact creation. (default: True)
            max_objects: The maximum number of objects to consider when adding a
                reference that points to directory or bucket store prefix. For S3 and
                GCS, this limit is 10,000 by default but is uncapped for other URI
                schemes. (default: None)

        Returns:
            The added manifest entries.

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.

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
            # All objects under `prefix/` will be added under `path/` at the artifact
            # root.
            artifact.add_reference("gs://mybucket/prefix", name="path")
            ```
        """
        self._ensure_can_add()
        if name is not None:
            name = LogicalPath(name)

        # This is a bit of a hack, we want to check if the uri is a of the type
        # ArtifactManifestEntry. If so, then recover the reference URL.
        if isinstance(uri, ArtifactManifestEntry):
            uri_str = uri.ref_url()
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
            self.manifest.add_entry(entry)

        return manifest_entries

    def add(self, obj: data_types.WBValue, name: StrPath) -> ArtifactManifestEntry:
        """Add wandb.WBValue `obj` to the artifact.

        Arguments:
            obj: The object to add. Currently support one of Bokeh, JoinedTable,
                PartitionedTable, Table, Classes, ImageMask, BoundingBoxes2D, Audio,
                Image, Video, Html, Object3D
            name: The path within the artifact to add the object.

        Returns:
            The added manifest entry

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized

        Examples:
            Basic usage:
            ```python
            artifact = wandb.Artifact("my_table", type="dataset")
            table = wandb.Table(
                columns=["a", "b", "c"], data=[(i, i * 2, 2**i) for i in range(10)]
            )
            artifact.add(table, "my_table")

            wandb.log_artifact(artifact)
            ```

            Retrieve an object:
            ```python
            artifact = wandb.use_artifact("my_table:latest")
            table = artifact.get("my_table")
            ```
        """
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
            return self._added_objs[obj_id][1]

        # If the object is coming from another artifact, save it as a reference
        ref_path = obj._get_artifact_entry_ref_url()
        if ref_path is not None:
            return self.add_reference(ref_path, type(obj).with_suffix(name))[0]

        val = obj.to_json(self)
        name = obj.with_suffix(name)
        entry = self.manifest.get_entry_by_path(name)
        if entry is not None:
            return entry

        def do_write(f: IO) -> None:
            import json

            # TODO: Do we need to open with utf-8 codec?
            f.write(json.dumps(val, sort_keys=True))

        if is_tmp_name:
            file_path = os.path.join(self._TMP_DIR.name, str(id(self)), name)
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
        # We store a reference to the obj so that its id doesn't get reused.
        self._added_objs[obj_id] = (obj, entry)
        if obj._artifact_target is None:
            obj._set_artifact_target(self, entry.path)

        if is_tmp_name:
            if os.path.exists(file_path):
                os.remove(file_path)

        return entry

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
            size=os.path.getsize(staging_path),
            local_path=staging_path,
        )

        self.manifest.add_entry(entry)
        self._added_local_paths[os.fspath(path)] = entry
        return entry

    def remove(self, item: Union[StrPath, "ArtifactManifestEntry"]) -> None:
        """Remove an item from the artifact.

        Arguments:
            item: the item to remove. Can be a specific manifest entry or the name of an
                artifact-relative path. If the item matches a directory all items in
                that directory will be removed.

        Raises:
            ArtifactFinalizedError: if the artifact has already been finalized.
            FileNotFoundError: if the item isn't found in the artifact.
        """
        self._ensure_can_add()

        if isinstance(item, ArtifactManifestEntry):
            self.manifest.remove_entry(item)
            return

        path = str(PurePosixPath(item))
        entry = self.manifest.get_entry_by_path(path)
        if entry:
            self.manifest.remove_entry(entry)
            return

        entries = self.manifest.get_entries_in_directory(path)
        if not entries:
            raise FileNotFoundError(f"No such file or directory: {path}")
        for entry in entries:
            self.manifest.remove_entry(entry)

    def get_path(self, name: StrPath) -> ArtifactManifestEntry:
        """Get the entry with the given name.

        Arguments:
            name: The artifact relative name to get

        Raises:
            ArtifactNotLoggedError: if the artifact isn't logged or the run is offline
            KeyError: if the artifact doesn't contain an entry with the given name

        Examples:
            Basic usage:
            ```python
            # Run logging the artifact
            with wandb.init() as r:
                artifact = wandb.Artifact("my_dataset", type="dataset")
                artifact.add_file("path/to/file.txt")
                wandb.log_artifact(artifact)

            # Run using the artifact
            with wandb.init() as r:
                artifact = r.use_artifact("my_dataset:latest")
                path = artifact.get_path("file.txt")

                # Can now download 'file.txt' directly:
                path.download()
            ```
        """
        self._ensure_logged("get_path")

        name = LogicalPath(name)
        entry = self.manifest.entries.get(name) or self._get_obj_entry(name)[0]
        if entry is None:
            raise KeyError("Path not contained in artifact: %s" % name)
        entry._parent_artifact = self
        return entry

    def get(self, name: str) -> Optional[data_types.WBValue]:
        """Get the WBValue object located at the artifact relative `name`.

        Arguments:
            name: The artifact relative name to get

        Raises:
            ArtifactNotLoggedError: if the artifact isn't logged or the run is offline

        Examples:
            Basic usage:
            ```python
            # Run logging the artifact
            with wandb.init() as r:
                artifact = wandb.Artifact("my_dataset", type="dataset")
                table = wandb.Table(
                    columns=["a", "b", "c"], data=[(i, i * 2, 2**i) for i in range(10)]
                )
                artifact.add(table, "my_table")
                wandb.log_artifact(artifact)

            # Run using the artifact
            with wandb.init() as r:
                artifact = r.use_artifact("my_dataset:latest")
                table = artifact.get("my_table")
            ```
        """
        self._ensure_logged("get")

        entry, wb_class = self._get_obj_entry(name)
        if entry is None or wb_class is None:
            return None

        # If the entry is a reference from another artifact, then get it directly from
        # that artifact.
        referenced_id = entry._referenced_artifact_id()
        if referenced_id:
            assert self._client is not None
            artifact = self._from_id(referenced_id, client=self._client)
            assert artifact is not None
            return artifact.get(util.uri_from_path(entry.ref))

        # Special case for wandb.Table. This is intended to be a short term
        # optimization. Since tables are likely to download many other assets in
        # artifact(s), we eagerly download the artifact using the parallelized
        # `artifact.download`. In the future, we should refactor the deserialization
        # pattern such that this special case is not needed.
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

    def get_added_local_path_name(self, local_path: str) -> Optional[str]:
        """Get the artifact relative name of a file added by a local filesystem path.

        Arguments:
            local_path: The local path to resolve into an artifact relative name.

        Returns:
            The artifact relative name.

        Examples:
            Basic usage:
            ```python
            artifact = wandb.Artifact("my_dataset", type="dataset")
            artifact.add_file("path/to/file.txt", name="artifact/path/file.txt")

            # Returns `artifact/path/file.txt`:
            name = artifact.get_added_local_path_name("path/to/file.txt")
            ```
        """
        entry = self._added_local_paths.get(local_path, None)
        if entry is None:
            return None
        return entry.path

    def _get_obj_entry(
        self, name: str
    ) -> Tuple[Optional["ArtifactManifestEntry"], Optional[Type[WBValue]]]:
        """Return an object entry by name, handling any type suffixes.

        When objects are added with `.add(obj, name)`, the name is typically changed to
        include the suffix of the object type when serializing to JSON. So we need to be
        able to resolve a name, without tasking the user with appending .THING.json.
        This method returns an entry if it exists by a suffixed name.

        Arguments:
            name: name used when adding
        """
        for wb_class in WBValue.type_mapping().values():
            wandb_file_name = wb_class.with_suffix(name)
            entry = self.manifest.entries.get(wandb_file_name)
            if entry is not None:
                return entry, wb_class
        return None, None

    # Downloading.

    def download(
        self,
        root: Optional[str] = None,
        recursive: bool = False,
        allow_missing_references: bool = False,
    ) -> FilePathStr:
        """Download the contents of the artifact to the specified root directory.

        NOTE: Any existing files at `root` are left untouched. Explicitly delete
        root before calling `download` if you want the contents of `root` to exactly
        match the artifact.

        Arguments:
            root: The directory in which to download this artifact's files.
            recursive: If true, then all dependent artifacts are eagerly downloaded.
                Otherwise, the dependent artifacts are downloaded as needed.

        Returns:
            The path to the downloaded contents.

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
        """
        self._ensure_logged("download")

        root = root or self._default_root()
        self._add_download_root(root)

        if wandb.run is None:
            with wandb.init(
                entity=self._source_entity,
                project=self._source_project,
                job_type="auto",
                settings=wandb.Settings(silent="true"),
            ):
                return self._run_artifact_download(
                    root=root,
                    recursive=recursive,
                    allow_missing_references=allow_missing_references,
                )
        else:
            return self._run_artifact_download(
                root=root,
                recursive=recursive,
                allow_missing_references=allow_missing_references,
            )

    def _run_artifact_download(
        self,
        root: str,
        recursive: bool = False,
        allow_missing_references: bool = False,
    ) -> FilePathStr:
        assert wandb.run is not None, "failed to initialize run"
        run = wandb.run
        if run._settings._require_nexus:
            if not run._backend or not run._backend.interface:
                raise NotImplementedError
            if run._settings._offline:
                raise NotImplementedError("cannot download in offline mode")
            handle = run._backend.interface.deliver_download_artifact(
                self.qualified_name,
                root,
                recursive,
                allow_missing_references,
            )
            # Start the download process in the user process too, to handle reference downloads
            self._download(
                root=root,
                recursive=recursive,
                allow_missing_references=allow_missing_references,
            )
            result = handle.wait(timeout=-1)
            if result is None:
                handle.abandon()
            assert result is not None
            response = result.response.download_artifact_response
            if response.error_message:
                raise ValueError(
                    f"Error downloading artifact: {response.error_message}"
                )
            download_path = response.file_download_path
            return FilePathStr(download_path)
        return self._download(
            root=root,
            recursive=recursive,
            allow_missing_references=allow_missing_references,
        )

    def _download(
        self,
        root: str,
        recursive: bool = False,
        allow_missing_references: bool = False,
    ) -> FilePathStr:
        # todo: remove once artifact reference downloads are supported in nexus
        require_nexus = False
        if wandb.run is not None:
            require_nexus = wandb.run._settings._require_nexus

        nfiles = len(self.manifest.entries)
        size = sum(e.size or 0 for e in self.manifest.entries.values())
        log = False
        if nfiles > 5000 or size > 50 * 1024 * 1024:
            log = True
            termlog(
                "Downloading large artifact {}, {:.2f}MB. {} files... ".format(
                    self.name, size / (1024 * 1024), nfiles
                ),
            )
            start_time = datetime.now()
        download_logger = ArtifactDownloadLogger(nfiles=nfiles)

        def _download_entry(
            entry: ArtifactManifestEntry,
            api_key: Optional[str],
            cookies: Optional[Dict],
            headers: Optional[Dict],
        ) -> None:
            _thread_local_api_settings.api_key = api_key
            _thread_local_api_settings.cookies = cookies
            _thread_local_api_settings.headers = headers

            try:
                entry.download(root)
            except FileNotFoundError as e:
                if allow_missing_references:
                    wandb.termwarn(str(e))
                    return
                raise
            download_logger.notify_downloaded()

        download_entry = partial(
            _download_entry,
            api_key=_thread_local_api_settings.api_key,
            cookies=_thread_local_api_settings.cookies,
            headers=_thread_local_api_settings.headers,
        )

        with concurrent.futures.ThreadPoolExecutor(64) as executor:
            active_futures = set()
            has_next_page = True
            cursor = None
            while has_next_page:
                fetch_url_batch_size = env.get_artifact_fetch_file_url_batch_size()
                attrs = self._fetch_file_urls(cursor, fetch_url_batch_size)
                has_next_page = attrs["pageInfo"]["hasNextPage"]
                cursor = attrs["pageInfo"]["endCursor"]
                for edge in attrs["edges"]:
                    entry = self.get_path(edge["node"]["name"])
                    if require_nexus and entry.ref is None:
                        # Handled by nexus
                        continue
                    entry._download_url = edge["node"]["directUrl"]
                    active_futures.add(executor.submit(download_entry, entry))
                # Wait for download threads to catch up.
                max_backlog = fetch_url_batch_size
                if len(active_futures) > max_backlog:
                    for future in concurrent.futures.as_completed(active_futures):
                        future.result()  # check for errors
                        active_futures.remove(future)
                        if len(active_futures) <= max_backlog:
                            break
            # Check for errors.
            for future in concurrent.futures.as_completed(active_futures):
                future.result()

        if recursive:
            for dependent_artifact in self._dependent_artifacts:
                dependent_artifact.download()

        if log:
            now = datetime.now()
            delta = abs((now - start_time).total_seconds())
            hours = int(delta // 3600)
            minutes = int((delta - hours * 3600) // 60)
            seconds = delta - hours * 3600 - minutes * 60
            termlog(
                f"Done. {hours}:{minutes}:{seconds:.1f}",
                prefix=False,
            )
        return FilePathStr(root)

    @retry.retriable(
        retry_timedelta=timedelta(minutes=3),
        retryable_exceptions=(requests.RequestException),
    )
    def _fetch_file_urls(
        self, cursor: Optional[str], per_page: Optional[int] = 5000
    ) -> Any:
        query = gql(
            """
            query ArtifactFileURLs($id: ID!, $cursor: String, $perPage: Int) {
                artifact(id: $id) {
                    files(after: $cursor, first: $perPage) {
                        pageInfo {
                            hasNextPage
                            endCursor
                        }
                        edges {
                            node {
                                name
                                directUrl
                            }
                        }
                    }
                }
            }
            """
        )
        assert self._client is not None
        response = self._client.execute(
            query,
            variable_values={"id": self.id, "cursor": cursor, "perPage": per_page},
            timeout=60,
        )
        return response["artifact"]["files"]

    def checkout(self, root: Optional[str] = None) -> str:
        """Replace the specified root directory with the contents of the artifact.

        WARNING: This will DELETE all files in `root` that are not included in the
        artifact.

        Arguments:
            root: The directory to replace with this artifact's files.

        Returns:
           The path to the checked out contents.

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
        """
        self._ensure_logged("checkout")

        root = root or self._default_root(include_version=False)

        for dirpath, _, files in os.walk(root):
            for file in files:
                full_path = os.path.join(dirpath, file)
                artifact_path = os.path.relpath(full_path, start=root)
                try:
                    self.get_path(artifact_path)
                except KeyError:
                    # File is not part of the artifact, remove it.
                    os.remove(full_path)

        return self.download(root=root)

    def verify(self, root: Optional[str] = None) -> None:
        """Verify that the actual contents of an artifact match the manifest.

        All files in the directory are checksummed and the checksums are then
        cross-referenced against the artifact's manifest.

        NOTE: References are not verified.

        Arguments:
            root: The directory to verify. If None artifact will be downloaded to
                './artifacts/self.name/'

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
            ValueError: If the verification fails.
        """
        self._ensure_logged("verify")

        root = root or self._default_root()

        for dirpath, _, files in os.walk(root):
            for file in files:
                full_path = os.path.join(dirpath, file)
                artifact_path = os.path.relpath(full_path, start=root)
                try:
                    self.get_path(artifact_path)
                except KeyError:
                    raise ValueError(
                        "Found file {} which is not a member of artifact {}".format(
                            full_path, self.name
                        )
                    )

        ref_count = 0
        for entry in self.manifest.entries.values():
            if entry.ref is None:
                if md5_file_b64(os.path.join(root, entry.path)) != entry.digest:
                    raise ValueError("Digest mismatch for file: %s" % entry.path)
            else:
                ref_count += 1
        if ref_count > 0:
            print("Warning: skipped verification of %s refs" % ref_count)

    def file(self, root: Optional[str] = None) -> StrPath:
        """Download a single file artifact to dir specified by the root.

        Arguments:
            root: The root directory in which to place the file. Defaults to
                './artifacts/self.name/'.

        Returns:
            The full path of the downloaded file.

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
            ValueError: if the artifact contains more than one file
        """
        self._ensure_logged("file")

        if root is None:
            root = os.path.join(".", "artifacts", self.name)

        if len(self.manifest.entries) > 1:
            raise ValueError(
                "This artifact contains more than one file, call `.download()` to get "
                'all files or call .get_path("filename").download()'
            )

        return self.get_path(list(self.manifest.entries)[0]).download(root)

    def files(
        self, names: Optional[List[str]] = None, per_page: int = 50
    ) -> ArtifactFiles:
        """Iterate over all files stored in this artifact.

        Arguments:
            names: The filename paths relative to the root of the artifact you wish to
                list.
            per_page: The number of files to return per request

        Returns:
            An iterator containing `File` objects

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
        """
        self._ensure_logged("files")
        return ArtifactFiles(self._client, self, names, per_page)

    def _default_root(self, include_version: bool = True) -> FilePathStr:
        name = self.source_name if include_version else self.source_name.split(":")[0]
        root = os.path.join(env.get_artifact_dir(), name)
        # In case we're on a system where the artifact dir has a name corresponding to
        # an unexpected filesystem, we'll check for alternate roots. If one exists we'll
        # use that, otherwise we'll fall back to the system-preferred path.
        path = filesystem.check_exists(root) or filesystem.system_preferred_path(root)
        return FilePathStr(str(path))

    def _add_download_root(self, dir_path: str) -> None:
        self._download_roots.add(os.path.abspath(dir_path))

    def _local_path_to_name(self, file_path: str) -> Optional[str]:
        """Convert a local file path to a path entry in the artifact."""
        abs_file_path = os.path.abspath(file_path)
        abs_file_parts = abs_file_path.split(os.sep)
        for i in range(len(abs_file_parts) + 1):
            if os.path.join(os.sep, *abs_file_parts[:i]) in self._download_roots:
                return os.path.join(*abs_file_parts[i:])
        return None

    # Others.

    def delete(self, delete_aliases: bool = False) -> None:
        """Delete an artifact and its files.

        Arguments:
            delete_aliases: If true, deletes all aliases associated with the artifact.
                Otherwise, this raises an exception if the artifact has existing
                aliases.

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged

        Examples:
            Delete all the "model" artifacts a run has logged:
            ```python
            runs = api.runs(path="my_entity/my_project")
            for run in runs:
                for artifact in run.logged_artifacts():
                    if artifact.type == "model":
                        artifact.delete(delete_aliases=True)
            ```
        """
        self._ensure_logged("delete")
        self._delete(delete_aliases)

    @normalize_exceptions
    def _delete(self, delete_aliases: bool = False) -> None:
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
        assert self._client is not None
        self._client.execute(
            mutation,
            variable_values={
                "artifactID": self.id,
                "deleteAliases": delete_aliases,
            },
        )

    @normalize_exceptions
    def link(self, target_path: str, aliases: Optional[List[str]] = None) -> None:
        """Link this artifact to a portfolio (a promoted collection of artifacts).

        Arguments:
            target_path: The path to the portfolio. It must take the form {portfolio},
                {project}/{portfolio} or {entity}/{project}/{portfolio}.
            aliases: A list of strings which uniquely identifies the artifact inside the
                specified portfolio.

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
        """
        if wandb.run is None:
            with wandb.init(
                entity=self._source_entity,
                project=self._source_project,
                job_type="auto",
                settings=wandb.Settings(silent="true"),
            ) as run:
                run.link_artifact(self, target_path, aliases)
        else:
            wandb.run.link_artifact(self, target_path, aliases)

    def used_by(self) -> List[Run]:
        """Get a list of the runs that have used this artifact.

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
        """
        self._ensure_logged("used_by")

        query = gql(
            """
            query ArtifactUsedBy(
                $id: ID!,
            ) {
                artifact(id: $id) {
                    usedBy {
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
        assert self._client is not None
        response = self._client.execute(
            query,
            variable_values={"id": self.id},
        )
        return [
            Run(
                self._client,
                edge["node"]["project"]["entityName"],
                edge["node"]["project"]["name"],
                edge["node"]["name"],
            )
            for edge in response.get("artifact", {}).get("usedBy", {}).get("edges", [])
        ]

    def logged_by(self) -> Optional[Run]:
        """Get the run that first logged this artifact.

        Raises:
            ArtifactNotLoggedError: if the artifact has not been logged
        """
        self._ensure_logged("logged_by")

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
        assert self._client is not None
        response = self._client.execute(
            query,
            variable_values={"id": self.id},
        )
        creator = response.get("artifact", {}).get("createdBy", {})
        if creator.get("name") is None:
            return None
        return Run(
            self._client,
            creator["project"]["entityName"],
            creator["project"]["name"],
            creator["name"],
        )

    def json_encode(self) -> Dict[str, Any]:
        self._ensure_logged("json_encode")
        return util.artifact_to_json(self)

    @staticmethod
    def _expected_type(
        entity_name: str, project_name: str, name: str, client: RetryingClient
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
        return (
            ((response.get("project") or {}).get("artifact") or {}).get("artifactType")
            or {}
        ).get("name")

    @staticmethod
    def _normalize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            raise TypeError(f"metadata must be dict, not {type(metadata)}")
        return cast(
            Dict[str, Any], json.loads(json.dumps(util.json_friendly_val(metadata)))
        )

    def _load_manifest(self, url: str) -> None:
        with requests.get(url) as request:
            request.raise_for_status()
            self._manifest = ArtifactManifest.from_manifest_json(
                json.loads(util.ensure_text(request.content))
            )
        for entry in self.manifest.entries.values():
            referenced_id = entry._referenced_artifact_id()
            if referenced_id:
                assert self._client is not None
                dep_artifact = self._from_id(referenced_id, client=self._client)
                assert dep_artifact is not None
                self._dependent_artifacts.add(dep_artifact)

    @staticmethod
    def _get_gql_artifact_fragment() -> str:
        fields = InternalApi().server_artifact_introspection()
        fragment = """
            fragment ArtifactFragment on Artifact {
                id
                artifactSequence {
                    project {
                        entityName
                        name
                    }
                    name
                }
                versionIndex
                artifactType {
                    name
                }
                description
                metadata
                ttlDurationSeconds
                ttlIsInherited
                aliases {
                    artifactCollection {
                        project {
                            entityName
                            name
                        }
                        name
                    }
                    alias
                }
                state
                commitHash
                fileCount
                createdAt
                updatedAt
            }
        """
        if "ttlIsInherited" not in fields:
            return fragment.replace("ttlDurationSeconds", "").replace(
                "ttlIsInherited", ""
            )
        return fragment

    def _ttl_duration_seconds_to_gql(self) -> Optional[int]:
        # Set artifact ttl value to ttl_duration_seconds if the user set a value
        # otherwise use ttl_status to indicate the backend INHERIT(-1) or DISABLED(-2) when the TTL is None
        # When ttl_change = None its a no op since nothing changed
        INHERIT = -1  # noqa: N806
        DISABLED = -2  # noqa: N806

        if not self._ttl_changed:
            return None
        if self._ttl_is_inherited:
            return INHERIT
        return self._ttl_duration_seconds or DISABLED

    def _ttl_duration_seconds_from_gql(
        self, gql_ttl_duration_seconds: Optional[int]
    ) -> Optional[int]:
        # If gql_ttl_duration_seconds is not positive, its indicating that TTL is DISABLED(-2)
        # gql_ttl_duration_seconds only returns None if the server is not compatible with setting Artifact TTLs
        if gql_ttl_duration_seconds and gql_ttl_duration_seconds > 0:
            return gql_ttl_duration_seconds
        return None


class _ArtifactVersionType(WBType):
    name = "artifactVersion"
    types = [Artifact]


TypeRegistry.add(_ArtifactVersionType)
