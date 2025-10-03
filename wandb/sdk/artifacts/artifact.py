"""Artifact class."""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import multiprocessing.dummy
import os
import re
import shutil
import stat
import tempfile
import time
from collections import deque
from concurrent.futures import Executor, ThreadPoolExecutor, as_completed
from copy import copy
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from itertools import filterfalse
from pathlib import Path, PurePosixPath
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Final,
    Iterator,
    Literal,
    Sequence,
    Type,
    final,
)
from urllib.parse import quote, urljoin, urlparse

import requests

import wandb
from wandb import data_types, env
from wandb._iterutils import one, unique_list
from wandb._strutils import nameof
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public import ArtifactCollection, ArtifactFiles, Run
from wandb.apis.public.utils import gql_compat
from wandb.data_types import WBValue
from wandb.errors import CommError
from wandb.errors.errors import UnsupportedError
from wandb.errors.term import termerror, termlog, termwarn
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto.wandb_deprecated import Deprecated
from wandb.sdk import wandb_setup
from wandb.sdk.artifacts.storage_policies._multipart import should_multipart_download
from wandb.sdk.data_types._dtypes import Type as WBType
from wandb.sdk.data_types._dtypes import TypeRegistry
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.lib import retry, runid, telemetry
from wandb.sdk.lib.deprecate import deprecate
from wandb.sdk.lib.filesystem import check_exists, system_preferred_path
from wandb.sdk.lib.hashutil import B64MD5, b64_to_hex_id, md5_file_b64
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr
from wandb.sdk.lib.runid import generate_id
from wandb.sdk.mailbox import MailboxHandle
from wandb.util import (
    alias_is_version_index,
    artifact_to_json,
    fsync_open,
    json_dumps_safer,
    uri_from_path,
    vendor_setup,
)

from ._factories import make_storage_policy
from ._generated import (
    ADD_ALIASES_GQL,
    ARTIFACT_BY_ID_GQL,
    ARTIFACT_BY_NAME_GQL,
    ARTIFACT_COLLECTION_MEMBERSHIP_FILE_URLS_GQL,
    ARTIFACT_CREATED_BY_GQL,
    ARTIFACT_FILE_URLS_GQL,
    ARTIFACT_TYPE_GQL,
    ARTIFACT_USED_BY_GQL,
    ARTIFACT_VIA_MEMBERSHIP_BY_NAME_GQL,
    DELETE_ALIASES_GQL,
    DELETE_ARTIFACT_GQL,
    FETCH_ARTIFACT_MANIFEST_GQL,
    FETCH_LINKED_ARTIFACTS_GQL,
    LINK_ARTIFACT_GQL,
    UNLINK_ARTIFACT_GQL,
    UPDATE_ARTIFACT_GQL,
    ArtifactAliasInput,
    ArtifactByID,
    ArtifactByName,
    ArtifactCollectionAliasInput,
    ArtifactCollectionMembershipFileUrls,
    ArtifactCreatedBy,
    ArtifactFileUrls,
    ArtifactFragment,
    ArtifactType,
    ArtifactUsedBy,
    ArtifactViaMembershipByName,
    FetchArtifactManifest,
    FetchLinkedArtifacts,
    FileUrlsFragment,
    LinkArtifact,
    LinkArtifactInput,
    MembershipWithArtifact,
    TagInput,
    UpdateArtifact,
)
from ._gqlutils import omit_artifact_fields, supports_enable_tracking_var, type_info
from ._validators import (
    LINKED_ARTIFACT_COLLECTION_TYPE,
    ArtifactPath,
    FullArtifactPath,
    _LinkArtifactFields,
    ensure_logged,
    ensure_not_finalized,
    is_artifact_registry_project,
    remove_registry_prefix,
    validate_aliases,
    validate_artifact_name,
    validate_artifact_type,
    validate_metadata,
    validate_tags,
    validate_ttl_duration_seconds,
)
from .artifact_download_logger import ArtifactDownloadLogger
from .artifact_instance_cache import artifact_instance_cache
from .artifact_manifest import ArtifactManifest
from .artifact_manifest_entry import ArtifactManifestEntry
from .artifact_manifests.artifact_manifest_v1 import ArtifactManifestV1
from .artifact_state import ArtifactState
from .artifact_ttl import ArtifactTTL
from .exceptions import (
    ArtifactNotLoggedError,
    TooFewItemsError,
    TooManyItemsError,
    WaitTimeoutError,
)
from .staging import get_staging_dir
from .storage_handlers.gcs_handler import _GCSIsADirectoryError

reset_path = vendor_setup()

from wandb_gql import gql  # noqa: E402

reset_path()

if TYPE_CHECKING:
    from wandb.apis.public import RetryingClient

logger = logging.getLogger(__name__)


_MB: Final[int] = 1024 * 1024


@final
@dataclass
class _DeferredArtifactManifest:
    """A lightweight wrapper around the manifest URL, used to indicate deferred loading of the actual manifest."""

    url: str


class Artifact:
    """Flexible and lightweight building block for dataset and model versioning.

    Construct an empty W&B Artifact. Populate an artifacts contents with methods that
    begin with `add`. Once the artifact has all the desired files, you can call
    `run.log_artifact()` to log it.

    Args:
        name (str): A human-readable name for the artifact. Use the name to identify
            a specific artifact in the W&B App UI or programmatically. You can
            interactively reference an artifact with the `use_artifact` Public API.
            A name can contain letters, numbers, underscores, hyphens, and dots.
            The name must be unique across a project.
        type (str): The artifact's type. Use the type of an artifact to both organize
            and differentiate artifacts. You can use any string that contains letters,
            numbers, underscores, hyphens, and dots. Common types include `dataset` or `model`.
            Include `model` within your type string if you want to link the artifact
            to the W&B Model Registry. Note that some types reserved for internal use
            and cannot be set by users. Such types include `job` and types that start with `wandb-`.
        description (str | None) = None: A description of the artifact. For Model or Dataset Artifacts,
            add documentation for your standardized team model or dataset card. View
            an artifact's description programmatically with the `Artifact.description`
            attribute or programmatically with the W&B App UI. W&B renders the
            description as markdown in the W&B App.
        metadata (dict[str, Any] | None) = None: Additional information about an artifact. Specify metadata as a
            dictionary of key-value pairs. You can specify no more than 100 total keys.
        incremental: Use `Artifact.new_draft()` method instead to modify an
            existing artifact.
        use_as: Deprecated.
        is_link: Boolean indication of if the artifact is a linked artifact(`True`) or source artifact(`False`).

    Returns:
        An `Artifact` object.
    """

    _TMP_DIR = tempfile.TemporaryDirectory("wandb-artifacts")
    atexit.register(_TMP_DIR.cleanup)

    def __init__(
        self,
        name: str,
        type: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        incremental: bool = False,
        use_as: str | None = None,
        storage_region: str | None = None,
    ) -> None:
        if not re.match(r"^[a-zA-Z0-9_\-.]+$", name):
            raise ValueError(
                f"Artifact name may only contain alphanumeric characters, dashes, "
                f"underscores, and dots. Invalid name: {name}"
            )

        from wandb.sdk.artifacts._internal_artifact import InternalArtifact

        if incremental and not isinstance(self, InternalArtifact):
            termwarn("Using experimental arg `incremental`")

        # Internal.
        self._client: RetryingClient | None = None

        self._tmp_dir: tempfile.TemporaryDirectory | None = None
        self._added_objs: dict[int, tuple[WBValue, ArtifactManifestEntry]] = {}
        self._added_local_paths: dict[str, ArtifactManifestEntry] = {}
        self._save_handle: MailboxHandle[pb.Result] | None = None
        self._download_roots: set[str] = set()
        # Set by new_draft(), otherwise the latest artifact will be used as the base.
        self._base_id: str | None = None
        # Properties.
        self._id: str | None = None
        self._client_id: str = runid.generate_id(128)
        self._sequence_client_id: str = runid.generate_id(128)
        self._entity: str | None = None
        self._project: str | None = None
        self._name: str = validate_artifact_name(name)  # includes version after saving
        self._version: str | None = None
        self._source_entity: str | None = None
        self._source_project: str | None = None
        self._source_name: str = name  # includes version after saving
        self._source_version: str | None = None
        self._source_artifact: Artifact | None = None
        self._is_link: bool = False
        self._type: str = validate_artifact_type(type, name)
        self._description: str | None = description
        self._metadata: dict[str, Any] = validate_metadata(metadata)
        self._ttl_duration_seconds: int | None = None
        self._ttl_is_inherited: bool = True
        self._ttl_changed: bool = False
        self._aliases: list[str] = []
        self._saved_aliases: list[str] = []
        self._tags: list[str] = []
        self._saved_tags: list[str] = []
        self._distributed_id: str | None = None
        self._incremental: bool = incremental
        if use_as is not None:
            deprecate(
                field_name=Deprecated.artifact__init_use_as,
                warning_message=(
                    "`use_as` argument is deprecated and does not affect the behaviour of `wandb.Artifact()`"
                ),
            )
        self._use_as: str | None = None
        self._state: ArtifactState = ArtifactState.PENDING
        self._manifest: ArtifactManifest | _DeferredArtifactManifest | None = (
            ArtifactManifestV1(storage_policy=make_storage_policy(storage_region))
        )
        self._commit_hash: str | None = None
        self._file_count: int | None = None
        self._created_at: str | None = None
        self._updated_at: str | None = None
        self._final: bool = False
        self._history_step: int | None = None
        self._linked_artifacts: list[Artifact] = []

        # Cache.
        artifact_instance_cache[self._client_id] = self

    def __repr__(self) -> str:
        return f"<Artifact {self.id or self.name}>"

    @classmethod
    def _from_id(cls, artifact_id: str, client: RetryingClient) -> Artifact | None:
        if cached_artifact := artifact_instance_cache.get(artifact_id):
            return cached_artifact

        query = gql_compat(ARTIFACT_BY_ID_GQL, omit_fields=omit_artifact_fields(client))

        data = client.execute(query, variable_values={"id": artifact_id})
        result = ArtifactByID.model_validate(data)

        if (artifact := result.artifact) is None:
            return None

        src_collection = artifact.artifact_sequence
        src_project = src_collection.project

        entity_name = src_project.entity_name if src_project else ""
        project_name = src_project.name if src_project else ""

        name = f"{src_collection.name}:v{artifact.version_index}"

        path = FullArtifactPath(prefix=entity_name, project=project_name, name=name)
        return cls._from_attrs(path, artifact, client)

    @classmethod
    def _membership_from_name(
        cls, *, path: FullArtifactPath, client: RetryingClient
    ) -> Artifact:
        if not InternalApi()._server_supports(
            pb.ServerFeature.PROJECT_ARTIFACT_COLLECTION_MEMBERSHIP
        ):
            raise UnsupportedError(
                "querying for the artifact collection membership is not supported "
                "by this version of wandb server. Consider updating to the latest version."
            )

        query = gql_compat(
            ARTIFACT_VIA_MEMBERSHIP_BY_NAME_GQL,
            omit_fields=omit_artifact_fields(client),
        )
        gql_vars = {
            "entityName": path.prefix,
            "projectName": path.project,
            "name": path.name,
        }
        data = client.execute(query, variable_values=gql_vars)
        result = ArtifactViaMembershipByName.model_validate(data)

        if not (project := result.project):
            raise ValueError(
                f"project {path.project!r} not found under entity {path.prefix!r}"
            )
        if not (membership := project.artifact_collection_membership):
            entity_project = f"{path.prefix}/{path.project}"
            raise ValueError(
                f"artifact membership {path.name!r} not found in {entity_project!r}"
            )
        return cls._from_membership(membership, target=path, client=client)

    @classmethod
    def _from_name(
        cls,
        *,
        path: FullArtifactPath,
        client: RetryingClient,
        enable_tracking: bool = False,
    ) -> Artifact:
        if InternalApi()._server_supports(
            pb.ServerFeature.PROJECT_ARTIFACT_COLLECTION_MEMBERSHIP
        ):
            return cls._membership_from_name(path=path, client=client)

        omit_vars = None if supports_enable_tracking_var(client) else {"enableTracking"}
        gql_vars = {
            "entityName": path.prefix,
            "projectName": path.project,
            "name": path.name,
            "enableTracking": enable_tracking,
        }
        query = gql_compat(
            ARTIFACT_BY_NAME_GQL,
            omit_variables=omit_vars,
            omit_fields=omit_artifact_fields(client),
        )
        data = client.execute(query, variable_values=gql_vars)
        result = ArtifactByName.model_validate(data)

        if not (project := result.project):
            raise ValueError(
                f"project {path.project!r} not found under entity {path.prefix!r}"
            )
        if not (artifact := project.artifact):
            entity_project = f"{path.prefix}/{path.project}"
            raise ValueError(f"artifact {path.name!r} not found in {entity_project!r}")

        return cls._from_attrs(path, artifact, client)

    @classmethod
    def _from_membership(
        cls,
        membership: MembershipWithArtifact,
        target: FullArtifactPath,
        client: RetryingClient,
    ) -> Artifact:
        if not (
            (collection := membership.artifact_collection)
            and (name := collection.name)
            and (proj := collection.project)
        ):
            raise ValueError("Missing artifact collection project in GraphQL response")

        if is_artifact_registry_project(proj.name) and (
            target.project == "model-registry"
        ):
            wandb.termwarn(
                "This model registry has been migrated and will be discontinued. "
                f"Your request was redirected to the corresponding artifact {name!r} in the new registry. "
                f"Please update your paths to point to the migrated registry directly, '{proj.name}/{name}'."
            )
            new_target = replace(target, prefix=proj.entity_name, project=proj.name)
        else:
            new_target = copy(target)

        if not (artifact := membership.artifact):
            raise ValueError(f"Artifact {target.to_str()!r} not found in response")

        return cls._from_attrs(new_target, artifact, client)

    @classmethod
    def _from_attrs(
        cls,
        path: FullArtifactPath,
        attrs: ArtifactFragment,
        client: RetryingClient,
        aliases: list[str] | None = None,
    ) -> Artifact:
        # Placeholder is required to skip validation.
        artifact = cls("placeholder", type="placeholder")
        artifact._client = client
        artifact._entity = path.prefix
        artifact._project = path.project
        artifact._name = path.name

        artifact._assign_attrs(attrs, aliases)

        artifact.finalize()

        # Cache.
        assert artifact.id is not None
        artifact_instance_cache[artifact.id] = artifact
        return artifact

    # TODO: Eventually factor out is_link. Have to currently use it since some forms of fetching the artifact
    # doesn't make it clear if the artifact is a link or not and have to manually set it.
    def _assign_attrs(
        self,
        art: ArtifactFragment,
        aliases: list[str] | None = None,
        is_link: bool | None = None,
    ) -> None:
        """Update this Artifact's attributes using the server response."""
        self._id = art.id

        src_collection = art.artifact_sequence
        src_project = src_collection.project

        self._source_entity = src_project.entity_name if src_project else ""
        self._source_project = src_project.name if src_project else ""
        self._source_name = f"{src_collection.name}:v{art.version_index}"
        self._source_version = f"v{art.version_index}"

        self._entity = self._entity or self._source_entity
        self._project = self._project or self._source_project
        self._name = self._name or self._source_name

        # TODO: Refactor artifact query to fetch artifact via membership instead
        # and get the collection type
        if is_link is None:
            self._is_link = (
                self._entity != self._source_entity
                or self._project != self._source_project
                or self._name.split(":")[0] != self._source_name.split(":")[0]
            )
        else:
            self._is_link = is_link

        self._type = art.artifact_type.name
        self._description = art.description

        # The future of aliases is to move all alias fetches to the membership level
        # so we don't have to do the collection fetches below
        if aliases:
            processed_aliases = aliases
        elif art.aliases:
            entity = self._entity
            project = self._project
            collection = self._name.split(":")[0]
            processed_aliases = [
                art_alias.alias
                for art_alias in art.aliases
                if (
                    (coll := art_alias.artifact_collection)
                    and (proj := coll.project)
                    and proj.entity_name == entity
                    and proj.name == project
                    and coll.name == collection
                )
            ]
        else:
            processed_aliases = []

        version_aliases = list(filter(alias_is_version_index, processed_aliases))
        other_aliases = list(filterfalse(alias_is_version_index, processed_aliases))

        try:
            version = one(
                version_aliases, too_short=TooFewItemsError, too_long=TooManyItemsError
            )
        except TooFewItemsError:
            version = f"v{art.version_index}"  # default to the source version
        except TooManyItemsError:
            msg = f"Expected at most one version alias, got {len(version_aliases)}: {version_aliases!r}"
            raise ValueError(msg) from None

        self._version = version
        self._name = self._name if (":" in self._name) else f"{self._name}:{version}"

        self._aliases = other_aliases
        self._saved_aliases = copy(self._aliases)

        self._tags = [tag.name for tag in (art.tags or [])]
        self._saved_tags = copy(self._tags)

        self._metadata = validate_metadata(art.metadata)

        self._ttl_duration_seconds = validate_ttl_duration_seconds(
            art.ttl_duration_seconds
        )
        self._ttl_is_inherited = (
            True if (art.ttl_is_inherited is None) else art.ttl_is_inherited
        )

        self._state = ArtifactState(art.state)

        self._manifest = (
            _DeferredArtifactManifest(manifest.file.direct_url)
            if (manifest := art.current_manifest)
            else None
        )

        self._commit_hash = art.commit_hash
        self._file_count = art.file_count
        self._created_at = art.created_at
        self._updated_at = art.updated_at
        self._history_step = art.history_step

    @ensure_logged
    def new_draft(self) -> Artifact:
        """Create a new draft artifact with the same content as this committed artifact.

        Modifying an existing artifact creates a new artifact version known
        as an "incremental artifact". The artifact returned can be extended or
        modified and logged as a new version.

        Returns:
            An `Artifact` object.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
        """
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

    # Properties (Python Class managed attributes).

    @property
    def id(self) -> str | None:
        """The artifact's ID."""
        if self.is_draft():
            return None
        assert self._id is not None
        return self._id

    @property
    @ensure_logged
    def entity(self) -> str:
        """The name of the entity that the artifact collection belongs to.

        If the artifact is a link, the entity will be the entity of the linked artifact.
        """
        assert self._entity is not None
        return self._entity

    @property
    @ensure_logged
    def project(self) -> str:
        """The name of the project that the artifact collection belongs to.

        If the artifact is a link, the project will be the project of the linked artifact.
        """
        assert self._project is not None
        return self._project

    @property
    def name(self) -> str:
        """The artifact name and version of the artifact.

        A string with the format `{collection}:{alias}`. If fetched before an artifact is logged/saved, the name won't contain the alias.
        If the artifact is a link, the name will be the name of the linked artifact.
        """
        return self._name

    @property
    def qualified_name(self) -> str:
        """The entity/project/name of the artifact.

        If the artifact is a link, the qualified name will be the qualified name of the linked artifact path.
        """
        return f"{self.entity}/{self.project}/{self.name}"

    @property
    @ensure_logged
    def version(self) -> str:
        """The artifact's version.

        A string with the format `v{number}`.
        If the artifact is a link artifact, the version will be from the linked collection.
        """
        assert self._version is not None
        return self._version

    @property
    @ensure_logged
    def collection(self) -> ArtifactCollection:
        """The collection this artifact was retrieved from.

        A collection is an ordered group of artifact versions.
        If this artifact was retrieved from a portfolio / linked collection, that
        collection will be returned rather than the collection
        that an artifact version originated from. The collection
        that an artifact originates from is known as the source sequence.
        """
        base_name = self.name.split(":")[0]
        return ArtifactCollection(
            self._client, self.entity, self.project, base_name, self.type
        )

    @property
    @ensure_logged
    def source_entity(self) -> str:
        """The name of the entity of the source artifact."""
        assert self._source_entity is not None
        return self._source_entity

    @property
    @ensure_logged
    def source_project(self) -> str:
        """The name of the project of the source artifact."""
        assert self._source_project is not None
        return self._source_project

    @property
    def source_name(self) -> str:
        """The artifact name and version of the source artifact.

        A string with the format `{source_collection}:{alias}`. Before the artifact is saved,
        contains only the name since the version is not yet known.
        """
        return self._source_name

    @property
    def source_qualified_name(self) -> str:
        """The source_entity/source_project/source_name of the source artifact."""
        return f"{self.source_entity}/{self.source_project}/{self.source_name}"

    @property
    @ensure_logged
    def source_version(self) -> str:
        """The source artifact's version.

        A string with the format `v{number}`.
        """
        assert self._source_version is not None
        return self._source_version

    @property
    @ensure_logged
    def source_collection(self) -> ArtifactCollection:
        """The artifact's source collection.

        The source collection is the collection that the artifact was logged from.
        """
        base_name = self.source_name.split(":")[0]
        return ArtifactCollection(
            self._client, self.source_entity, self.source_project, base_name, self.type
        )

    @property
    def is_link(self) -> bool:
        """Boolean flag indicating if the artifact is a link artifact.

        True: The artifact is a link artifact to a source artifact.
        False: The artifact is a source artifact.
        """
        return self._is_link

    @property
    @ensure_logged
    def linked_artifacts(self) -> list[Artifact]:
        """Returns a list of all the linked artifacts of a source artifact.

        If the artifact is a link artifact (`artifact.is_link == True`), it will return an empty list.
        Limited to 500 results."""
        if not self.is_link:
            self._linked_artifacts = self._fetch_linked_artifacts()
        return self._linked_artifacts

    @property
    @ensure_logged
    def source_artifact(self) -> Artifact:
        """Returns the source artifact. The source artifact is the original logged artifact.

        If the artifact itself is a source artifact (`artifact.is_link == False`), it will return itself."""
        if not self.is_link:
            return self
        if self._source_artifact is None:
            if self._client is None:
                raise ValueError("Client is not initialized")

            try:
                path = FullArtifactPath(
                    prefix=self.source_entity,
                    project=self.source_project,
                    name=self.source_name,
                )
                self._source_artifact = self._from_name(path=path, client=self._client)
            except Exception as e:
                raise ValueError(
                    f"Unable to fetch source artifact for linked artifact {self.name}"
                ) from e
        return self._source_artifact

    @property
    def type(self) -> str:
        """The artifact's type. Common types include `dataset` or `model`."""
        return self._type

    @property
    @ensure_logged
    def url(self) -> str:
        """
        Constructs the URL of the artifact.

        Returns:
            str: The URL of the artifact.
        """
        try:
            base_url = self._client.app_url  # type: ignore[union-attr]
        except AttributeError:
            return ""

        if not self.is_link:
            return self._construct_standard_url(base_url)
        if is_artifact_registry_project(self.project):
            return self._construct_registry_url(base_url)
        if self._type == "model" or self.project == "model-registry":
            return self._construct_model_registry_url(base_url)
        return self._construct_standard_url(base_url)

    def _construct_standard_url(self, base_url: str) -> str:
        if not all(
            [
                base_url,
                self.entity,
                self.project,
                self._type,
                self.collection.name,
                self._version,
            ]
        ):
            return ""
        return urljoin(
            base_url,
            f"{self.entity}/{self.project}/artifacts/{quote(self._type)}/{quote(self.collection.name)}/{self._version}",
        )

    def _construct_registry_url(self, base_url: str) -> str:
        if not all(
            [
                base_url,
                self.entity,
                self.project,
                self.collection.name,
                self._version,
            ]
        ):
            return ""

        try:
            org, *_ = InternalApi()._fetch_orgs_and_org_entities_from_entity(
                self.entity
            )
        except ValueError:
            return ""

        selection_path = quote(
            f"{self.entity}/{self.project}/{self.collection.name}", safe=""
        )
        return urljoin(
            base_url,
            f"orgs/{org.display_name}/registry/{remove_registry_prefix(self.project)}?selectionPath={selection_path}&view=membership&version={self.version}",
        )

    def _construct_model_registry_url(self, base_url: str) -> str:
        if not all(
            [
                base_url,
                self.entity,
                self.project,
                self.collection.name,
                self._version,
            ]
        ):
            return ""
        selection_path = quote(
            f"{self.entity}/{self.project}/{self.collection.name}", safe=""
        )
        return urljoin(
            base_url,
            f"{self.entity}/registry/model?selectionPath={selection_path}&view=membership&version={self._version}",
        )

    @property
    def description(self) -> str | None:
        """A description of the artifact."""
        return self._description

    @description.setter
    def description(self, description: str | None) -> None:
        """Set the description of the artifact.

        For model or dataset Artifacts, add documentation for your
        standardized team model or dataset card. In the W&B UI the
        description is rendered as markdown.

        Editing the description will apply the changes to the source artifact and all linked artifacts associated with it.

        Args:
            description: Free text that offers a description of the artifact.
        """
        if self.is_link:
            wandb.termwarn(
                "Editing the description of this linked artifact will edit the description for the source artifact and it's linked artifacts as well."
            )
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
        Editing the metadata will apply the changes to the source artifact and all linked artifacts associated with it.

        Args:
            metadata: Structured data associated with the artifact.
        """
        if self.is_link:
            wandb.termwarn(
                "Editing the metadata of this linked artifact will edit the metadata for the source artifact and it's linked artifacts as well."
            )
        self._metadata = validate_metadata(metadata)

    @property
    def ttl(self) -> timedelta | None:
        """The time-to-live (TTL) policy of an artifact.

        Artifacts are deleted shortly after a TTL policy's duration passes.
        If set to `None`, the artifact deactivates TTL policies and will be not
        scheduled for deletion, even if there is a team default TTL.
        An artifact inherits a TTL policy from
        the team default if the team administrator defines a default
        TTL and there is no custom policy set on an artifact.

        Raises:
            ArtifactNotLoggedError: Unable to fetch inherited TTL if the
            artifact has not been logged or saved.
        """
        if self._ttl_is_inherited and (self.is_draft() or self._ttl_changed):
            raise ArtifactNotLoggedError(f"{nameof(type(self))}.ttl", self)
        if self._ttl_duration_seconds is None:
            return None
        return timedelta(seconds=self._ttl_duration_seconds)

    @ttl.setter
    def ttl(self, ttl: timedelta | ArtifactTTL | None) -> None:
        """The time-to-live (TTL) policy of an artifact.

        Artifacts are deleted shortly after a TTL policy's duration passes.
        If set to `None`, the artifact has no TTL policy set and it is not
        scheduled for deletion. An artifact inherits a TTL policy from
        the team default if the team administrator defines a default
        TTL and there is no custom policy set on an artifact.

        Args:
            ttl: The duration as a positive Python `datetime.timedelta` Type
                that represents how long the artifact will remain active from its creation.

        """
        if self.type == "wandb-history":
            raise ValueError("Cannot set artifact TTL for type wandb-history")

        if self.is_link:
            raise ValueError(
                "Cannot set TTL for link artifact. "
                "Unlink the artifact first then set the TTL for the source artifact"
            )

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
    @ensure_logged
    def aliases(self) -> list[str]:
        """List of one or more semantically-friendly references or

        identifying "nicknames" assigned to an artifact version.

        Aliases are mutable references that you can programmatically reference.
        Change an artifact's alias with the W&B App UI or programmatically.
        See [Create new artifact versions](https://docs.wandb.ai/guides/artifacts/create-a-new-artifact-version)
        for more information.
        """
        return self._aliases

    @aliases.setter
    @ensure_logged
    def aliases(self, aliases: list[str]) -> None:
        """Set the aliases associated with this artifact."""
        self._aliases = validate_aliases(aliases)

    @property
    @ensure_logged
    def tags(self) -> list[str]:
        """List of one or more tags assigned to this artifact version."""
        return self._tags

    @tags.setter
    @ensure_logged
    def tags(self, tags: list[str]) -> None:
        """Set the tags associated with this artifact.

        Editing tags will apply the changes to the source artifact and all linked artifacts associated with it.
        """
        if self.is_link:
            wandb.termwarn(
                "Editing tags will apply the changes to the source artifact and all linked artifacts associated with it."
            )
        self._tags = validate_tags(tags)

    @property
    def distributed_id(self) -> str | None:
        """The distributed ID of the artifact.

        <!-- lazydoc-ignore: internal -->
        """
        return self._distributed_id

    @distributed_id.setter
    def distributed_id(self, distributed_id: str | None) -> None:
        self._distributed_id = distributed_id

    @property
    def incremental(self) -> bool:
        """Boolean flag indicating if the artifact is an incremental artifact.

        <!-- lazydoc-ignore: internal -->
        """
        return self._incremental

    @property
    def use_as(self) -> str | None:
        """Deprecated."""
        deprecate(
            field_name=Deprecated.artifact__use_as,
            warning_message=("The use_as property of Artifact is deprecated."),
        )
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
        if isinstance(self._manifest, _DeferredArtifactManifest):
            # A deferred manifest URL flags a deferred download request,
            # so fetch the manifest to override the placeholder object
            self._manifest = self._load_manifest(self._manifest.url)
            return self._manifest

        if self._manifest is None:
            if self._client is None:
                raise RuntimeError("Client not initialized for artifact queries")

            query = gql(FETCH_ARTIFACT_MANIFEST_GQL)
            gql_vars = {
                "entityName": self.entity,
                "projectName": self.project,
                "name": self.name,
            }
            data = self._client.execute(query, variable_values=gql_vars)
            result = FetchArtifactManifest.model_validate(data)
            if not (
                (project := result.project)
                and (artifact := project.artifact)
                and (manifest := artifact.current_manifest)
            ):
                raise ValueError("Failed to fetch artifact manifest")
            self._manifest = self._load_manifest(manifest.file.direct_url)

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
        return sum(entry.size for entry in self.manifest.entries.values() if entry.size)

    @property
    @ensure_logged
    def commit_hash(self) -> str:
        """The hash returned when this artifact was committed."""
        assert self._commit_hash is not None
        return self._commit_hash

    @property
    @ensure_logged
    def file_count(self) -> int:
        """The number of files (including references)."""
        assert self._file_count is not None
        return self._file_count

    @property
    @ensure_logged
    def created_at(self) -> str:
        """Timestamp when the artifact was created."""
        assert self._created_at is not None
        return self._created_at

    @property
    @ensure_logged
    def updated_at(self) -> str:
        """The time when the artifact was last updated."""
        assert self._created_at is not None
        return self._updated_at or self._created_at

    @property
    @ensure_logged
    def history_step(self) -> int | None:
        """The nearest step at which history metrics were logged for the source run of the artifact.

        Examples:
        ```python
        run = artifact.logged_by()
        if run and (artifact.history_step is not None):
            history = run.sample_history(
                min_step=artifact.history_step,
                max_step=artifact.history_step + 1,
                keys=["my_metric"],
            )
        ```
        """
        if self._history_step is None:
            return None
        return max(0, self._history_step - 1)

    # State management.

    def finalize(self) -> None:
        """Finalize the artifact version.

        You cannot modify an artifact version once it is finalized because the artifact
        is logged as a specific artifact version. Create a new artifact version
        to log more data to an artifact. An artifact is automatically finalized
        when you log the artifact with `log_artifact`.
        """
        self._final = True

    def is_draft(self) -> bool:
        """Check if artifact is not saved.

        Returns:
            Boolean. `False` if artifact is saved. `True` if artifact is not saved.
        """
        return self._state is ArtifactState.PENDING

    def _is_draft_save_started(self) -> bool:
        return self._save_handle is not None

    def save(
        self,
        project: str | None = None,
        settings: wandb.Settings | None = None,
    ) -> None:
        """Persist any changes made to the artifact.

        If currently in a run, that run will log this artifact. If not currently in a
        run, a run of type "auto" is created to track this artifact.

        Args:
            project: A project to use for the artifact in the case that a run is not
                already in context.
            settings: A settings object to use when initializing an automatic run. Most
                commonly used in testing harness.
        """
        if self._state is not ArtifactState.PENDING:
            return self._update()

        if self._incremental:
            with telemetry.context() as tel:
                tel.feature.artifact_incremental = True

        if run := wandb_setup.singleton().most_recent_active_run:
            # TODO: Deprecate and encourage explicit log_artifact().
            run.log_artifact(self)
        else:
            if settings is None:
                settings = wandb.Settings(silent="true")
            with wandb.init(  # type: ignore
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

    def _set_save_handle(
        self,
        save_handle: MailboxHandle[pb.Result],
        client: RetryingClient,
    ) -> None:
        self._save_handle = save_handle
        self._client = client

    def wait(self, timeout: int | None = None) -> Artifact:
        """If needed, wait for this artifact to finish logging.

        Args:
            timeout: The time, in seconds, to wait.

        Returns:
            An `Artifact` object.
        """
        if self.is_draft():
            if self._save_handle is None:
                raise ArtifactNotLoggedError(nameof(self.wait), self)

            try:
                result = self._save_handle.wait_or(timeout=timeout)
            except TimeoutError as e:
                raise WaitTimeoutError(
                    "Artifact upload wait timed out, failed to fetch Artifact response"
                ) from e

            response = result.response.log_artifact_response
            if response.error_message:
                raise ValueError(response.error_message)
            self._populate_after_save(response.artifact_id)
        return self

    def _populate_after_save(self, artifact_id: str) -> None:
        assert self._client is not None

        query = gql_compat(
            ARTIFACT_BY_ID_GQL, omit_fields=omit_artifact_fields(self._client)
        )
        data = self._client.execute(query, variable_values={"id": artifact_id})
        result = ArtifactByID.model_validate(data)

        if not (artifact := result.artifact):
            raise ValueError(f"Unable to fetch artifact with id: {artifact_id!r}")

        # _populate_after_save is only called on source artifacts, not linked artifacts
        # We have to manually set is_link because we aren't fetching the collection the artifact.
        # That requires greater refactoring for commitArtifact to return the artifact collection type.
        self._assign_attrs(artifact, is_link=False)

    @normalize_exceptions
    def _update(self) -> None:
        """Persists artifact changes to the wandb backend."""
        if self._client is None:
            raise RuntimeError("Client not initialized for artifact mutations")

        entity = self.entity
        project = self.project
        collection = self.name.split(":")[0]

        aliases = None

        if type_info(self._client, "AddAliasesInput") is not None:
            # wandb backend version >= 0.13.0
            alias_props = {
                "entity_name": entity,
                "project_name": project,
                "artifact_collection_name": collection,
            }
            if aliases_to_add := (set(self.aliases) - set(self._saved_aliases)):
                add_mutation = gql(ADD_ALIASES_GQL)
                add_alias_inputs = [
                    ArtifactCollectionAliasInput(**alias_props, alias=alias)
                    for alias in aliases_to_add
                ]
                try:
                    self._client.execute(
                        add_mutation,
                        variable_values={
                            "artifactID": self.id,
                            "aliases": [a.model_dump() for a in add_alias_inputs],
                        },
                    )
                except CommError as e:
                    raise CommError(
                        "You do not have permission to add"
                        f" {'at least one of the following aliases' if len(aliases_to_add) > 1 else 'the following alias'}"
                        f" to this artifact: {aliases_to_add}"
                    ) from e

            if aliases_to_delete := (set(self._saved_aliases) - set(self.aliases)):
                delete_mutation = gql(DELETE_ALIASES_GQL)
                delete_alias_inputs = [
                    ArtifactCollectionAliasInput(**alias_props, alias=alias)
                    for alias in aliases_to_delete
                ]
                try:
                    self._client.execute(
                        delete_mutation,
                        variable_values={
                            "artifactID": self.id,
                            "aliases": [a.model_dump() for a in delete_alias_inputs],
                        },
                    )
                except CommError as e:
                    raise CommError(
                        f"You do not have permission to delete"
                        f" {'at least one of the following aliases' if len(aliases_to_delete) > 1 else 'the following alias'}"
                        f" from this artifact: {aliases_to_delete}"
                    ) from e

            self._saved_aliases = copy(self.aliases)

        else:  # wandb backend version < 0.13.0
            aliases = [
                ArtifactAliasInput(
                    artifact_collection_name=collection, alias=alias
                ).model_dump()
                for alias in self.aliases
            ]

        omit_fields = omit_artifact_fields(self._client)
        omit_variables = set()

        if {"ttlIsInherited", "ttlDurationSeconds"} & omit_fields:
            if self._ttl_changed:
                termwarn(
                    "Server not compatible with setting Artifact TTLs, please upgrade the server to use Artifact TTL"
                )

            omit_variables |= {"ttlDurationSeconds"}

        tags_to_add = validate_tags(set(self.tags) - set(self._saved_tags))
        tags_to_del = validate_tags(set(self._saved_tags) - set(self.tags))

        if {"tags"} & omit_fields:
            if tags_to_add or tags_to_del:
                termwarn(
                    "Server not compatible with Artifact tags. "
                    "To use Artifact tags, please upgrade the server to v0.85 or higher."
                )

            omit_variables |= {"tagsToAdd", "tagsToDelete"}

        mutation = gql_compat(
            UPDATE_ARTIFACT_GQL,
            omit_variables=omit_variables,
            omit_fields=omit_fields,
        )

        gql_vars = {
            "artifactID": self.id,
            "description": self.description,
            "metadata": json_dumps_safer(self.metadata),
            "ttlDurationSeconds": self._ttl_duration_seconds_to_gql(),
            "aliases": aliases,
            "tagsToAdd": [TagInput(tag_name=t).model_dump() for t in tags_to_add],
            "tagsToDelete": [TagInput(tag_name=t).model_dump() for t in tags_to_del],
        }

        data = self._client.execute(mutation, variable_values=gql_vars)

        result = UpdateArtifact.model_validate(data).update_artifact
        if not (result and (artifact := result.artifact)):
            raise ValueError("Unable to parse updateArtifact response")
        self._assign_attrs(artifact)

        self._ttl_changed = False  # Reset after updating artifact

    # Adding, removing, getting entries.

    def __getitem__(self, name: str) -> WBValue | None:
        """Get the WBValue object located at the artifact relative `name`.

        Args:
            name: The artifact relative name to get.

        Returns:
            W&B object that can be logged with `run.log()` and visualized in the W&B UI.

        Raises:
            ArtifactNotLoggedError: If the artifact isn't logged or the run is offline.
        """
        return self.get(name)

    def __setitem__(self, name: str, item: WBValue) -> ArtifactManifestEntry:
        """Add `item` to the artifact at path `name`.

        Args:
            name: The path within the artifact to add the object.
            item: The object to add.

        Returns:
            The added manifest entry

        Raises:
            ArtifactFinalizedError: You cannot make changes to the current
            artifact version because it is finalized. Log a new artifact
            version instead.
        """
        return self.add(item, name)

    @contextlib.contextmanager
    @ensure_not_finalized
    def new_file(
        self, name: str, mode: str = "x", encoding: str | None = None
    ) -> Iterator[IO]:
        """Open a new temporary file and add it to the artifact.

        Args:
            name: The name of the new file to add to the artifact.
            mode: The file access mode to use to open the new file.
            encoding: The encoding used to open the new file.

        Returns:
            A new file object that can be written to. Upon closing, the file
            is automatically added to the artifact.

        Raises:
            ArtifactFinalizedError: You cannot make changes to the current
            artifact version because it is finalized. Log a new artifact
            version instead.
        """
        overwrite: bool = "x" not in mode

        if self._tmp_dir is None:
            self._tmp_dir = tempfile.TemporaryDirectory()
        path = os.path.join(self._tmp_dir.name, name.lstrip("/"))

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        try:
            with fsync_open(path, mode, encoding) as f:
                yield f
        except FileExistsError:
            raise ValueError(f"File with name {name!r} already exists at {path!r}")
        except UnicodeEncodeError as e:
            termerror(
                f"Failed to open the provided file ({nameof(type(e))}: {e}). Please "
                f"provide the proper encoding."
            )
            raise

        self.add_file(
            path, name=name, policy="immutable", skip_cache=True, overwrite=overwrite
        )

    @ensure_not_finalized
    def add_file(
        self,
        local_path: str,
        name: str | None = None,
        is_tmp: bool | None = False,
        skip_cache: bool | None = False,
        policy: Literal["mutable", "immutable"] | None = "mutable",
        overwrite: bool = False,
    ) -> ArtifactManifestEntry:
        """Add a local file to the artifact.

        Args:
            local_path: The path to the file being added.
            name: The path within the artifact to use for the file being added.
                Defaults to the basename of the file.
            is_tmp: If true, then the file is renamed deterministically to avoid
                collisions.
            skip_cache: If `True`, do not copy files to the cache
                after uploading.
            policy: By default, set to "mutable". If set to "mutable",
                create a temporary copy of the file to prevent corruption
                during upload. If set to "immutable", disable
                protection and rely on the user not to delete or change the
                file.
            overwrite: If `True`, overwrite the file if it already exists.

        Returns:
            The added manifest entry.

        Raises:
            ArtifactFinalizedError: You cannot make changes to the current
                artifact version because it is finalized. Log a new artifact
                version instead.
            ValueError: Policy must be "mutable" or "immutable"
        """
        if not os.path.isfile(local_path):
            raise ValueError(f"Path is not a file: {local_path!r}")

        name = LogicalPath(name or os.path.basename(local_path))
        digest = md5_file_b64(local_path)

        if is_tmp:
            file_path, file_name = os.path.split(name)
            file_name_parts = file_name.split(".")
            file_name_parts[0] = b64_to_hex_id(digest)[:20]
            name = os.path.join(file_path, ".".join(file_name_parts))

        return self._add_local_file(
            name,
            local_path,
            digest=digest,
            skip_cache=skip_cache,
            policy=policy,
            overwrite=overwrite,
        )

    @ensure_not_finalized
    def add_dir(
        self,
        local_path: str,
        name: str | None = None,
        skip_cache: bool | None = False,
        policy: Literal["mutable", "immutable"] | None = "mutable",
        merge: bool = False,
    ) -> None:
        """Add a local directory to the artifact.

        Args:
            local_path: The path of the local directory.
            name: The subdirectory name within an artifact. The name you
                specify appears in the W&B App UI nested by artifact's `type`.
                Defaults to the root of the artifact.
            skip_cache: If set to `True`, W&B will not copy/move files to
                the cache while uploading
            policy: By default, "mutable".
            - mutable: Create a temporary copy of the file to prevent corruption during upload.
            - immutable: Disable protection, rely on the user not to delete or change the file.
            merge: If `False` (default), throws ValueError if a file was already added in a previous add_dir call
                and its content has changed. If `True`, overwrites existing files with changed content.
                Always adds new files and never removes files. To replace an entire directory, pass a name when adding the directory
                using `add_dir(local_path, name=my_prefix)` and call `remove(my_prefix)` to remove the directory, then add it again.

        Raises:
            ArtifactFinalizedError: You cannot make changes to the current
                artifact version because it is finalized. Log a new artifact
                version instead.
            ValueError: Policy must be "mutable" or "immutable"
        """
        if not os.path.isdir(local_path):
            raise ValueError(f"Path is not a directory: {local_path!r}")

        termlog(
            f"Adding directory to artifact ({Path('.', local_path)})... ",
            newline=False,
        )
        start_time = time.monotonic()

        paths: deque[tuple[str, str]] = deque()
        logical_root = name or ""  # shared prefix, if any, for logical paths
        for dirpath, _, filenames in os.walk(local_path, followlinks=True):
            for fname in filenames:
                physical_path = os.path.join(dirpath, fname)
                logical_path = os.path.relpath(physical_path, start=local_path)
                logical_path = os.path.join(logical_root, logical_path)
                paths.append((logical_path, physical_path))

        def add_manifest_file(logical_pth: str, physical_pth: str) -> None:
            self._add_local_file(
                name=logical_pth,
                path=physical_pth,
                skip_cache=skip_cache,
                policy=policy,
                overwrite=merge,
            )

        num_threads = 8
        pool = multiprocessing.dummy.Pool(num_threads)
        pool.starmap(add_manifest_file, paths)
        pool.close()
        pool.join()

        termlog("Done. %.1fs" % (time.monotonic() - start_time), prefix=False)

    @ensure_not_finalized
    def add_reference(
        self,
        uri: ArtifactManifestEntry | str,
        name: StrPath | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> Sequence[ArtifactManifestEntry]:
        """Add a reference denoted by a URI to the artifact.

        Unlike files or directories that you add to an artifact, references are not
        uploaded to W&B. For more information,
        see [Track external files](https://docs.wandb.ai/guides/artifacts/track-external-files).

        By default, the following schemes are supported:

        - http(s): The size and digest of the file will be inferred by the
          `Content-Length` and the `ETag` response headers returned by the server.
        - s3: The checksum and size are pulled from the object metadata.
          If bucket versioning is enabled, then the version ID is also tracked.
        - gs: The checksum and size are pulled from the object metadata. If bucket
          versioning is enabled, then the version ID is also tracked.
        - https, domain matching `*.blob.core.windows.net`
        - Azure: The checksum and size are be pulled from the blob metadata.
          If storage account versioning is enabled, then the version ID is
          also tracked.
        - file: The checksum and size are pulled from the file system. This scheme
          is useful if you have an NFS share or other externally mounted volume
          containing files you wish to track but not necessarily upload.

        For any other scheme, the digest is just a hash of the URI and the size is left
        blank.

        Args:
            uri: The URI path of the reference to add. The URI path can be an object
                returned from `Artifact.get_entry` to store a reference to another
                artifact's entry.
            name: The path within the artifact to place the contents of this reference.
            checksum: Whether or not to checksum the resource(s) located at the
                reference URI. Checksumming is strongly recommended as it enables
                automatic integrity validation. Disabling checksumming will speed up
                artifact creation but reference directories will not iterated through so the
                objects in the directory will not be saved to the artifact. We recommend
                setting `checksum=False` when adding reference objects, in which case
                a new version will only be created if the reference URI changes.
            max_objects: The maximum number of objects to consider when adding a
                reference that points to directory or bucket store prefix.
                By default, the maximum number of objects allowed for Amazon S3,
                GCS, Azure, and local files is 10,000,000. Other URI schemas
                do not have a maximum.

        Returns:
            The added manifest entries.

        Raises:
            ArtifactFinalizedError: You cannot make changes to the current
            artifact version because it is finalized. Log a new artifact
            version instead.
        """
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

        manifest_entries = self.manifest.storage_policy.store_reference(
            self,
            URIStr(uri_str),
            name=name,
            checksum=checksum,
            max_objects=max_objects,
        )
        for entry in manifest_entries:
            self.manifest.add_entry(entry)

        return manifest_entries

    @ensure_not_finalized
    def add(
        self, obj: WBValue, name: StrPath, overwrite: bool = False
    ) -> ArtifactManifestEntry:
        """Add wandb.WBValue `obj` to the artifact.

        Args:
            obj: The object to add. Currently support one of Bokeh, JoinedTable,
                PartitionedTable, Table, Classes, ImageMask, BoundingBoxes2D,
                Audio, Image, Video, Html, Object3D
            name: The path within the artifact to add the object.
            overwrite: If True, overwrite existing objects with the same file
                path if applicable.

        Returns:
            The added manifest entry

        Raises:
            ArtifactFinalizedError: You cannot make changes to the current
            artifact version because it is finalized. Log a new artifact
            version instead.
        """
        name = LogicalPath(name)

        # This is a "hack" to automatically rename tables added to
        # the wandb /media/tables directory to their sha-based name.
        # TODO: figure out a more appropriate convention.
        is_tmp_name = name.startswith("media/tables")

        # Validate that the object is one of the correct wandb.Media types
        # TODO: move this to checking subclass of wandb.Media once all are
        # generally supported
        allowed_types = (
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
        )
        if not isinstance(obj, allowed_types):
            raise TypeError(
                f"Found object of type {obj.__class__}, expected one of:"
                f" {allowed_types}"
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
        if (not overwrite) and (entry is not None):
            return entry

        if is_tmp_name:
            file_path = os.path.join(self._TMP_DIR.name, str(id(self)), name)
            folder_path, _ = os.path.split(file_path)
            os.makedirs(folder_path, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as tmp_f:
                json.dump(val, tmp_f, sort_keys=True)
        else:
            filemode = "w" if overwrite else "x"
            with self.new_file(name, mode=filemode, encoding="utf-8") as f:
                json.dump(val, f, sort_keys=True)
                file_path = f.name

        # Note, we add the file from our temp directory.
        # It will be added again later on finalize, but succeed since
        # the checksum should match
        entry = self.add_file(file_path, name, is_tmp_name)
        # We store a reference to the obj so that its id doesn't get reused.
        self._added_objs[obj_id] = (obj, entry)
        if obj._artifact_target is None:
            obj._set_artifact_target(self, entry.path)

        if is_tmp_name:
            with contextlib.suppress(FileNotFoundError):
                os.remove(file_path)

        return entry

    def _add_local_file(
        self,
        name: StrPath,
        path: StrPath,
        digest: B64MD5 | None = None,
        skip_cache: bool | None = False,
        policy: Literal["mutable", "immutable"] | None = "mutable",
        overwrite: bool = False,
    ) -> ArtifactManifestEntry:
        policy = policy or "mutable"
        if policy not in ["mutable", "immutable"]:
            raise ValueError(
                f"Invalid policy {policy!r}. Policy may only be `mutable` or `immutable`."
            )
        upload_path = path
        if policy == "mutable":
            with tempfile.NamedTemporaryFile(dir=get_staging_dir(), delete=False) as f:
                staging_path = f.name
                shutil.copyfile(path, staging_path)
                # Set as read-only to prevent changes to the file during upload process
                os.chmod(staging_path, stat.S_IRUSR)
                upload_path = staging_path

        entry = ArtifactManifestEntry(
            path=name,
            digest=digest or md5_file_b64(upload_path),
            size=os.path.getsize(upload_path),
            local_path=upload_path,
            skip_cache=skip_cache,
        )
        self.manifest.add_entry(entry, overwrite=overwrite)
        self._added_local_paths[os.fspath(path)] = entry
        return entry

    @ensure_not_finalized
    def remove(self, item: StrPath | ArtifactManifestEntry) -> None:
        """Remove an item from the artifact.

        Args:
            item: The item to remove. Can be a specific manifest entry
                or the name of an artifact-relative path. If the item
                matches a directory all items in that directory will be removed.

        Raises:
            ArtifactFinalizedError: You cannot make changes to the current
                artifact version because it is finalized. Log a new artifact
                version instead.
            FileNotFoundError: If the item isn't found in the artifact.
        """
        if isinstance(item, ArtifactManifestEntry):
            self.manifest.remove_entry(item)
            return

        path = str(PurePosixPath(item))
        if entry := self.manifest.get_entry_by_path(path):
            return self.manifest.remove_entry(entry)

        entries = self.manifest.get_entries_in_directory(path)
        if not entries:
            raise FileNotFoundError(f"No such file or directory: {path}")
        for entry in entries:
            self.manifest.remove_entry(entry)

    def get_path(self, name: StrPath) -> ArtifactManifestEntry:
        """Deprecated. Use `get_entry(name)`."""
        deprecate(
            field_name=Deprecated.artifact__get_path,
            warning_message="Artifact.get_path(name) is deprecated, use Artifact.get_entry(name) instead.",
        )
        return self.get_entry(name)

    @ensure_logged
    def get_entry(self, name: StrPath) -> ArtifactManifestEntry:
        """Get the entry with the given name.

        Args:
            name: The artifact relative name to get

        Returns:
            A `W&B` object.

        Raises:
            ArtifactNotLoggedError: if the artifact isn't logged or the run is offline.
            KeyError: if the artifact doesn't contain an entry with the given name.
        """
        name = LogicalPath(name)
        entry = self.manifest.entries.get(name) or self._get_obj_entry(name)[0]
        if entry is None:
            raise KeyError(f"Path not contained in artifact: {name}")
        entry._parent_artifact = self
        return entry

    @ensure_logged
    def get(self, name: str) -> WBValue | None:
        """Get the WBValue object located at the artifact relative `name`.

        Args:
            name: The artifact relative name to retrieve.

        Returns:
            W&B object that can be logged with `run.log()` and
            visualized in the W&B UI.

        Raises:
            ArtifactNotLoggedError: if the artifact isn't logged or the
                run is offline.
        """
        entry, wb_class = self._get_obj_entry(name)
        if entry is None or wb_class is None:
            return None

        # If the entry is a reference from another artifact, then get it directly from
        # that artifact.
        if referenced_id := entry._referenced_artifact_id():
            assert self._client is not None
            artifact = self._from_id(referenced_id, client=self._client)
            assert artifact is not None
            return artifact.get(uri_from_path(entry.ref))

        # Special case for wandb.Table. This is intended to be a short term
        # optimization. Since tables are likely to download many other assets in
        # artifact(s), we eagerly download the artifact using the parallelized
        # `artifact.download`. In the future, we should refactor the deserialization
        # pattern such that this special case is not needed.
        if wb_class == wandb.Table:
            self.download()

        # Get the ArtifactManifestEntry
        item = self.get_entry(entry.path)
        item_path = item.download()

        # Load the object from the JSON blob
        with open(item_path) as file:
            json_obj = json.load(file)

        result = wb_class.from_json(json_obj, self)
        result._set_artifact_source(self, name)
        return result

    def get_added_local_path_name(self, local_path: str) -> str | None:
        """Get the artifact relative name of a file added by a local filesystem path.

        Args:
            local_path: The local path to resolve into an artifact relative name.

        Returns:
            The artifact relative name.
        """
        if entry := self._added_local_paths.get(local_path):
            return entry.path
        return None

    def _get_obj_entry(
        self, name: str
    ) -> tuple[ArtifactManifestEntry, Type[WBValue]] | tuple[None, None]:  # noqa: UP006  # `type` shadows `Artifact.type`
        """Return an object entry by name, handling any type suffixes.

        When objects are added with `.add(obj, name)`, the name is typically changed to
        include the suffix of the object type when serializing to JSON. So we need to be
        able to resolve a name, without tasking the user with appending .THING.json.
        This method returns an entry if it exists by a suffixed name.

        Args:
            name: name used when adding
        """
        for wb_class in WBValue.type_mapping().values():
            wandb_file_name = wb_class.with_suffix(name)
            if entry := self.manifest.entries.get(wandb_file_name):
                return entry, wb_class
        return None, None

    # Downloading.

    @ensure_logged
    def download(
        self,
        root: StrPath | None = None,
        allow_missing_references: bool = False,
        skip_cache: bool | None = None,
        path_prefix: StrPath | None = None,
        multipart: bool | None = None,
    ) -> FilePathStr:
        """Download the contents of the artifact to the specified root directory.

        Existing files located within `root` are not modified. Explicitly delete `root`
        before you call `download` if you want the contents of `root` to exactly match
        the artifact.

        Args:
            root: The directory W&B stores the artifact's files.
            allow_missing_references: If set to `True`, any invalid reference paths
                will be ignored while downloading referenced files.
            skip_cache: If set to `True`, the artifact cache will be skipped when
                downloading and W&B will download each file into the default root or
                specified download directory.
            path_prefix: If specified, only files with a path that starts with the given
                prefix will be downloaded. Uses unix format (forward slashes).
            multipart: If set to `None` (default), the artifact will be downloaded
                in parallel using multipart download if individual file size is greater than
                2GB. If set to `True` or `False`, the artifact will be downloaded in
                parallel or serially regardless of the file size.

        Returns:
            The path to the downloaded contents.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
        """
        root = FilePathStr(root or self._default_root())
        self._add_download_root(root)

        # TODO: download artifacts using core when implemented
        # if is_require_core():
        #     return self._download_using_core(
        #         root=root,
        #         allow_missing_references=allow_missing_references,
        #         skip_cache=bool(skip_cache),
        #         path_prefix=path_prefix,
        #     )
        return self._download(
            root=root,
            allow_missing_references=allow_missing_references,
            skip_cache=skip_cache,
            path_prefix=path_prefix,
            multipart=multipart,
        )

    def _download_using_core(
        self,
        root: str,
        allow_missing_references: bool = False,
        skip_cache: bool = False,
        path_prefix: StrPath | None = None,
    ) -> FilePathStr:
        import pathlib

        from wandb.sdk.backend.backend import Backend

        # TODO: Create a special stream instead of relying on an existing run.
        if wandb.run is None:
            wl = wandb_setup.singleton()

            stream_id = generate_id()

            settings = wl.settings.to_proto()
            # TODO: remove this
            tmp_dir = pathlib.Path(tempfile.mkdtemp())

            settings.sync_dir.value = str(tmp_dir)
            settings.sync_file.value = str(tmp_dir / f"{stream_id}.wandb")
            settings.files_dir.value = str(tmp_dir / "files")
            settings.run_id.value = stream_id

            service = wl.ensure_service()
            service.inform_init(settings=settings, run_id=stream_id)

            backend = Backend(settings=wl.settings, service=service)
            backend.ensure_launched()

            assert backend.interface
            backend.interface._stream_id = stream_id  # type: ignore
        else:
            assert wandb.run._backend
            backend = wandb.run._backend

        assert backend.interface
        handle = backend.interface.deliver_download_artifact(
            self.id,  # type: ignore
            root,
            allow_missing_references,
            skip_cache,
            path_prefix,  # type: ignore
        )
        # TODO: Start the download process in the user process too, to handle reference downloads
        self._download(
            root=root,
            allow_missing_references=allow_missing_references,
            skip_cache=skip_cache,
            path_prefix=path_prefix,
        )
        result = handle.wait_or(timeout=None)

        response = result.response.download_artifact_response
        if response.error_message:
            raise ValueError(f"Error downloading artifact: {response.error_message}")

        return FilePathStr(root)

    def _download(
        self,
        root: str,
        allow_missing_references: bool = False,
        skip_cache: bool | None = None,
        path_prefix: StrPath | None = None,
        multipart: bool | None = None,
    ) -> FilePathStr:
        nfiles = len(self.manifest.entries)
        size_mb = self.size / _MB

        if log := (nfiles > 5000 or size_mb > 50):
            termlog(
                f"Downloading large artifact {self.name!r}, {size_mb:.2f}MB. {nfiles!r} files...",
            )
            start_time = time.monotonic()

        download_logger = ArtifactDownloadLogger(nfiles=nfiles)

        def _download_entry(entry: ArtifactManifestEntry, executor: Executor) -> None:
            multipart_executor = (
                executor
                if should_multipart_download(entry.size, override=multipart)
                else None
            )
            try:
                entry.download(root, skip_cache=skip_cache, executor=multipart_executor)
            except FileNotFoundError as e:
                if allow_missing_references:
                    wandb.termwarn(str(e))
                    return
                raise
            except _GCSIsADirectoryError as e:
                logger.debug(str(e))
                return
            download_logger.notify_downloaded()

        def _init_thread(
            api_key: str | None, cookies: dict | None, headers: dict | None
        ) -> None:
            """Initialize the thread-local API settings in the CURRENT thread."""
            _thread_local_api_settings.api_key = api_key
            _thread_local_api_settings.cookies = cookies
            _thread_local_api_settings.headers = headers

        with ThreadPoolExecutor(
            max_workers=64,
            initializer=_init_thread,
            initargs=(
                _thread_local_api_settings.api_key,
                _thread_local_api_settings.cookies,
                _thread_local_api_settings.headers,
            ),
        ) as executor:
            batch_size = env.get_artifact_fetch_file_url_batch_size()

            active_futures = set()
            cursor, has_more = None, True
            while has_more:
                files_page = self._fetch_file_urls(cursor=cursor, per_page=batch_size)

                has_more = files_page.page_info.has_next_page
                cursor = files_page.page_info.end_cursor

                # `File` nodes are formally nullable, so filter them out just in case.
                file_nodes = (e.node for e in files_page.edges if e.node)
                for node in file_nodes:
                    entry = self.get_entry(node.name)
                    # TODO: uncomment once artifact downloads are supported in core
                    # if require_core and entry.ref is None:
                    #     # Handled by core
                    #     continue
                    entry._download_url = node.direct_url
                    if (not path_prefix) or entry.path.startswith(str(path_prefix)):
                        active_futures.add(
                            executor.submit(_download_entry, entry, executor=executor)
                        )

                # Wait for download threads to catch up.
                #
                # Extra context and observations (tonyyli):
                # - Even though the ThreadPoolExecutor limits the number of
                #   concurrently-executed tasks, its internal task queue is unbounded.
                #   The code below seems intended to ensure that at most `batch_size`
                #   "backlogged" futures are held in memory at any given time.  This seems like
                #   a reasonable safeguard against unbounded memory consumption.
                #
                # - We should probably use a builtin (bounded) Queue or Semaphore here instead.
                #   Consider this for a future change, or (depending on risk and risk tolerance)
                #   managing this logic via asyncio instead, if viable.
                if len(active_futures) > batch_size:
                    for future in as_completed(active_futures):
                        future.result()  # check for errors
                        active_futures.remove(future)
                        if len(active_futures) <= batch_size:
                            break

            # Check for errors.
            for future in as_completed(active_futures):
                future.result()

        if log:
            # If you're wondering if we can display a `timedelta`, note that it
            # doesn't really support custom string format specifiers (compared to
            # e.g. `datetime` objs).  To truncate the number of decimal places for
            # the seconds part, we manually convert/format each part below.
            dt_secs = abs(time.monotonic() - start_time)
            hrs, mins = divmod(dt_secs, 3600)
            mins, secs = divmod(mins, 60)
            termlog(
                f"Done. {int(hrs):02d}:{int(mins):02d}:{secs:04.1f} ({size_mb / dt_secs:.1f}MB/s)",
                prefix=False,
            )
        return FilePathStr(root)

    @retry.retriable(
        retry_timedelta=timedelta(minutes=3),
        retryable_exceptions=(requests.RequestException),
    )
    def _fetch_file_urls(
        self, cursor: str | None, per_page: int = 5000
    ) -> FileUrlsFragment:
        if self._client is None:
            raise RuntimeError("Client not initialized")

        if InternalApi()._server_supports(
            pb.ServerFeature.ARTIFACT_COLLECTION_MEMBERSHIP_FILES
        ):
            query = gql(ARTIFACT_COLLECTION_MEMBERSHIP_FILE_URLS_GQL)
            gql_vars = {
                "entityName": self.entity,
                "projectName": self.project,
                "artifactName": self.name.split(":")[0],
                "artifactVersionIndex": self.version,
                "cursor": cursor,
                "perPage": per_page,
            }
            data = self._client.execute(query, variable_values=gql_vars, timeout=60)
            result = ArtifactCollectionMembershipFileUrls.model_validate(data)

            if not (
                (project := result.project)
                and (collection := project.artifact_collection)
                and (membership := collection.artifact_membership)
                and (files := membership.files)
            ):
                raise ValueError(f"Unable to fetch files for artifact: {self.name!r}")
            return files
        else:
            query = gql(ARTIFACT_FILE_URLS_GQL)
            gql_vars = {"id": self.id, "cursor": cursor, "perPage": per_page}
            data = self._client.execute(query, variable_values=gql_vars, timeout=60)
            result = ArtifactFileUrls.model_validate(data)

            if not ((artifact := result.artifact) and (files := artifact.files)):
                raise ValueError(f"Unable to fetch files for artifact: {self.name!r}")
            return files

    @ensure_logged
    def checkout(self, root: str | None = None) -> str:
        """Replace the specified root directory with the contents of the artifact.

        WARNING: This will delete all files in `root` that are not included in the
        artifact.

        Args:
            root: The directory to replace with this artifact's files.

        Returns:
           The path of the checked out contents.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
        """
        root = root or self._default_root(include_version=False)

        for dirpath, _, files in os.walk(root):
            for file in files:
                full_path = os.path.join(dirpath, file)
                artifact_path = os.path.relpath(full_path, start=root)
                try:
                    self.get_entry(artifact_path)
                except KeyError:
                    # File is not part of the artifact, remove it.
                    os.remove(full_path)

        return self.download(root=root)

    @ensure_logged
    def verify(self, root: str | None = None) -> None:
        """Verify that the contents of an artifact match the manifest.

        All files in the directory are checksummed and the checksums are then
        cross-referenced against the artifact's manifest. References are not verified.

        Args:
            root: The directory to verify. If None artifact will be downloaded to
                './artifacts/self.name/'.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
            ValueError: If the verification fails.
        """
        root = root or self._default_root()

        for dirpath, _, files in os.walk(root):
            for file in files:
                full_path = os.path.join(dirpath, file)
                artifact_path = os.path.relpath(full_path, start=root)
                try:
                    self.get_entry(artifact_path)
                except KeyError:
                    raise ValueError(
                        f"Found file {full_path} which is not a member of artifact {self.name}"
                    )

        ref_count = 0
        for entry in self.manifest.entries.values():
            if entry.ref is None:
                if md5_file_b64(os.path.join(root, entry.path)) != entry.digest:
                    raise ValueError(f"Digest mismatch for file: {entry.path}")
            else:
                ref_count += 1
        if ref_count > 0:
            termwarn(f"skipped verification of {ref_count} refs")

    @ensure_logged
    def file(self, root: str | None = None) -> StrPath:
        """Download a single file artifact to the directory you specify with `root`.

        Args:
            root: The root directory to store the file. Defaults to
                `./artifacts/self.name/`.

        Returns:
            The full path of the downloaded file.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
            ValueError: If the artifact contains more than one file.
        """
        if root is None:
            root = os.path.join(".", "artifacts", self.name)

        if len(self.manifest.entries) > 1:
            raise ValueError(
                "This artifact contains more than one file, call `.download()` to get "
                'all files or call .get_entry("filename").download()'
            )

        return self.get_entry(list(self.manifest.entries)[0]).download(root)

    @ensure_logged
    def files(
        self, names: list[str] | None = None, per_page: int = 50
    ) -> ArtifactFiles:
        """Iterate over all files stored in this artifact.

        Args:
            names: The filename paths relative to the root of the artifact you wish to
                list.
            per_page: The number of files to return per request.

        Returns:
            An iterator containing `File` objects.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
        """
        return ArtifactFiles(self._client, self, names, per_page)

    def _default_root(self, include_version: bool = True) -> FilePathStr:
        name = self.source_name if include_version else self.source_name.split(":")[0]
        root = os.path.join(env.get_artifact_dir(), name)
        # In case we're on a system where the artifact dir has a name corresponding to
        # an unexpected filesystem, we'll check for alternate roots. If one exists we'll
        # use that, otherwise we'll fall back to the system-preferred path.
        return FilePathStr(check_exists(root) or system_preferred_path(root))

    def _add_download_root(self, dir_path: str) -> None:
        self._download_roots.add(os.path.abspath(dir_path))

    def _local_path_to_name(self, file_path: str) -> str | None:
        """Convert a local file path to a path entry in the artifact."""
        abs_file_path = os.path.abspath(file_path)
        abs_file_parts = abs_file_path.split(os.sep)
        for i in range(len(abs_file_parts) + 1):
            if os.path.join(os.sep, *abs_file_parts[:i]) in self._download_roots:
                return os.path.join(*abs_file_parts[i:])
        return None

    # Others.

    @ensure_logged
    def delete(self, delete_aliases: bool = False) -> None:
        """Delete an artifact and its files.

        If called on a linked artifact, only the link is deleted, and the
        source artifact is unaffected.

        Use `artifact.unlink()` instead of `artifact.delete()` to remove a link between a source artifact and a linked artifact.

        Args:
            delete_aliases: If set to `True`, deletes all aliases associated
                with the artifact. Otherwise, this raises an exception if
                the artifact has existing aliases. This parameter is ignored
                if the artifact is linked (a member of a portfolio collection).

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
        """
        if self.is_link:
            wandb.termwarn(
                "Deleting a link artifact will only unlink the artifact from the source artifact and not delete the source artifact and the data of the source artifact."
            )
            self._unlink()
        else:
            self._delete(delete_aliases)

    @normalize_exceptions
    def _delete(self, delete_aliases: bool = False) -> None:
        if self._client is None:
            raise RuntimeError("Client not initialized for artifact mutations")

        mutation = gql(DELETE_ARTIFACT_GQL)
        gql_vars = {"artifactID": self.id, "deleteAliases": delete_aliases}

        self._client.execute(mutation, variable_values=gql_vars)

    @normalize_exceptions
    def link(self, target_path: str, aliases: list[str] | None = None) -> Artifact:
        """Link this artifact to a portfolio (a promoted collection of artifacts).

        Args:
            target_path: The path to the portfolio inside a project.
                The target path must adhere to one of the following
                schemas `{portfolio}`, `{project}/{portfolio}` or
                `{entity}/{project}/{portfolio}`.
                To link the artifact to the Model Registry, rather than to a generic
                portfolio inside a project, set `target_path` to the following
                schema `{"model-registry"}/{Registered Model Name}` or
                `{entity}/{"model-registry"}/{Registered Model Name}`.
            aliases: A list of strings that uniquely identifies the artifact
                inside the specified portfolio.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.

        Returns:
            The linked artifact.
        """
        from wandb import Api

        if self.is_link:
            wandb.termwarn(
                "Linking to a link artifact will result in directly linking to the source artifact of that link artifact."
            )

        if self._client is None:
            raise ValueError("Client not initialized for artifact mutations")

        # Save the artifact first if necessary
        if self.is_draft():
            if not self._is_draft_save_started():
                self.save(project=self.source_project)

            # Wait until the artifact is committed before trying to link it.
            self.wait()

        api = InternalApi()
        settings = api.settings()

        target = ArtifactPath.from_str(target_path).with_defaults(
            project=settings.get("project") or "uncategorized",
        )

        # Parse the entity (first part of the path) appropriately,
        # depending on whether we're linking to a registry
        if target.is_registry_path():
            # In a Registry linking, the entity is used to fetch the organization of the artifact
            # therefore the source artifact's entity is passed to the backend
            org = target.prefix or settings.get("organization") or ""
            target.prefix = api._resolve_org_entity_name(self.source_entity, org)
        else:
            target = target.with_defaults(prefix=self.source_entity)

        # Explicitly convert to FullArtifactPath to ensure all fields are present
        target = FullArtifactPath(**asdict(target))

        # Prepare the validated GQL input, send it
        alias_inputs = [
            ArtifactAliasInput(artifact_collection_name=target.name, alias=a)
            for a in (aliases or [])
        ]
        gql_input = LinkArtifactInput(
            artifact_id=self.id,
            artifact_portfolio_name=target.name,
            entity_name=target.prefix,
            project_name=target.project,
            aliases=alias_inputs,
        )
        gql_vars = {"input": gql_input.model_dump(exclude_none=True)}

        # Newer server versions can return `artifactMembership` directly in the response,
        # avoiding the need to re-fetch the linked artifact at the end.
        if api._server_supports(
            pb.ServerFeature.ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE
        ):
            omit_fragments = set()
        else:
            # FIXME: Make `gql_compat` omit nested fragment definitions recursively (but safely)
            omit_fragments = {
                "MembershipWithArtifact",
                "ArtifactFragment",
                "ArtifactFragmentWithoutAliases",
            }

        gql_op = gql_compat(LINK_ARTIFACT_GQL, omit_fragments=omit_fragments)
        data = self._client.execute(gql_op, variable_values=gql_vars)
        result = LinkArtifact.model_validate(data).link_artifact

        # Newer server versions can return artifactMembership directly in the response
        if result and (membership := result.artifact_membership):
            return self._from_membership(membership, target=target, client=self._client)

        # Fallback to old behavior, which requires re-fetching the linked artifact to return it
        if not (result and (version_idx := result.version_index) is not None):
            raise ValueError("Unable to parse linked artifact version from response")

        link_name = f"{target.to_str()}:v{version_idx}"
        return Api(overrides={"entity": self.source_entity})._artifact(link_name)

    @ensure_logged
    def unlink(self) -> None:
        """Unlink this artifact if it is currently a member of a promoted collection of artifacts.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
            ValueError: If the artifact is not linked, in other words,
            it is not a member of a portfolio collection.
        """
        # Fail early if this isn't a linked artifact to begin with
        if not self.is_link:
            raise ValueError(
                f"Artifact {self.qualified_name!r} is not a linked artifact and cannot be unlinked.  "
                f"To delete it, use {nameof(self.delete)!r} instead."
            )

        self._unlink()

    @normalize_exceptions
    def _unlink(self) -> None:
        if self._client is None:
            raise RuntimeError("Client not initialized for artifact mutations")

        mutation = gql(UNLINK_ARTIFACT_GQL)
        gql_vars = {"artifactID": self.id, "artifactPortfolioID": self.collection.id}

        try:
            self._client.execute(mutation, variable_values=gql_vars)
        except CommError as e:
            raise CommError(
                f"You do not have permission to unlink the artifact {self.qualified_name}"
            ) from e

    @ensure_logged
    def used_by(self) -> list[Run]:
        """Get a list of the runs that have used this artifact and its linked artifacts.

        Returns:
            A list of `Run` objects.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
        """
        if self._client is None:
            raise RuntimeError("Client not initialized for artifact queries")

        query = gql(ARTIFACT_USED_BY_GQL)
        gql_vars = {"id": self.id}
        data = self._client.execute(query, variable_values=gql_vars)
        result = ArtifactUsedBy.model_validate(data)

        if (
            (artifact := result.artifact)
            and (used_by := artifact.used_by)
            and (edges := used_by.edges)
        ):
            run_nodes = (e.node for e in edges)
            return [
                Run(self._client, proj.entity_name, proj.name, run.name)
                for run in run_nodes
                if (proj := run.project)
            ]
        return []

    @ensure_logged
    def logged_by(self) -> Run | None:
        """Get the W&B run that originally logged the artifact.

        Returns:
            The name of the W&B run that originally logged the artifact.

        Raises:
            ArtifactNotLoggedError: If the artifact is not logged.
        """
        if self._client is None:
            raise RuntimeError("Client not initialized for artifact queries")

        query = gql(ARTIFACT_CREATED_BY_GQL)
        gql_vars = {"id": self.id}
        data = self._client.execute(query, variable_values=gql_vars)
        result = ArtifactCreatedBy.model_validate(data)

        if (
            (artifact := result.artifact)
            and (creator := artifact.created_by)
            and (name := creator.name)
            and (project := creator.project)
        ):
            return Run(self._client, project.entity_name, project.name, name)
        return None

    @ensure_logged
    def json_encode(self) -> dict[str, Any]:
        """Returns the artifact encoded to the JSON format.

        Returns:
            A `dict` with `string` keys representing attributes of the artifact.
        """
        return artifact_to_json(self)

    @staticmethod
    def _expected_type(
        entity_name: str, project_name: str, name: str, client: RetryingClient
    ) -> str | None:
        """Returns the expected type for a given artifact name and project."""
        query = gql(ARTIFACT_TYPE_GQL)
        gql_vars = {
            "entityName": entity_name,
            "projectName": project_name,
            "name": name if (":" in name) else f"{name}:latest",
        }
        data = client.execute(query, variable_values=gql_vars)
        result = ArtifactType.model_validate(data)

        if (
            (project := result.project)
            and (artifact := project.artifact)
            and (artifact_type := artifact.artifact_type)
        ):
            return artifact_type.name
        return None

    def _load_manifest(self, url: str) -> ArtifactManifest:
        with requests.get(url) as response:
            response.raise_for_status()
            return ArtifactManifest.from_manifest_json(response.json())

    def _ttl_duration_seconds_to_gql(self) -> int | None:
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

    def _fetch_linked_artifacts(self) -> list[Artifact]:
        """Fetches all linked artifacts from the server."""
        if self.id is None:
            raise ValueError(
                "Unable to find any artifact memberships for artifact without an ID"
            )
        if self._client is None:
            raise ValueError("Client is not initialized")
        response = self._client.execute(
            gql_compat(FETCH_LINKED_ARTIFACTS_GQL),
            variable_values={"artifactID": self.id},
        )
        result = FetchLinkedArtifacts.model_validate(response)

        if not (
            (artifact := result.artifact)
            and (memberships := artifact.artifact_memberships)
            and (membership_edges := memberships.edges)
        ):
            raise ValueError("Unable to find any artifact memberships for artifact")

        linked_artifacts: deque[Artifact] = deque()
        linked_nodes = (
            node
            for edge in membership_edges
            if (
                (node := edge.node)
                and (col := node.artifact_collection)
                and (col.typename__ == LINKED_ARTIFACT_COLLECTION_TYPE)
            )
        )
        for node in linked_nodes:
            alias_names = unique_list(a.alias for a in node.aliases)
            version = f"v{node.version_index}"
            aliases = (
                [*alias_names, version]
                if version not in alias_names
                else [*alias_names]
            )

            if not (
                node
                and (col := node.artifact_collection)
                and (proj := col.project)
                and (proj.entity_name and proj.name)
            ):
                raise ValueError("Unable to fetch fields for linked artifact")

            link_fields = _LinkArtifactFields(
                entity_name=proj.entity_name,
                project_name=proj.name,
                name=f"{col.name}:{version}",
                version=version,
                aliases=aliases,
            )
            link = self._create_linked_artifact_using_source_artifact(link_fields)
            linked_artifacts.append(link)
        return list(linked_artifacts)

    def _create_linked_artifact_using_source_artifact(
        self,
        link_fields: _LinkArtifactFields,
    ) -> Artifact:
        """Copies the source artifact to a linked artifact."""
        linked_artifact = copy(self)
        linked_artifact._version = link_fields.version
        linked_artifact._aliases = link_fields.aliases
        linked_artifact._saved_aliases = copy(link_fields.aliases)
        linked_artifact._name = link_fields.name
        linked_artifact._entity = link_fields.entity_name
        linked_artifact._project = link_fields.project_name
        linked_artifact._is_link = link_fields.is_link
        linked_artifact._linked_artifacts = link_fields.linked_artifacts
        return linked_artifact


class _ArtifactVersionType(WBType):
    name = "artifactVersion"
    types = [Artifact]


TypeRegistry.add(_ArtifactVersionType)
