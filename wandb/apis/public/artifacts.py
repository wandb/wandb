"""W&B Public API for Artifact objects.

This module provides classes for interacting with W&B artifacts and their
collections.
"""

from __future__ import annotations

import json
import re
from copy import copy
from typing import TYPE_CHECKING, Any, Iterable, Literal, Mapping, Sequence

from typing_extensions import override
from wandb_gql import Client, gql

import wandb
from wandb._strutils import nameof
from wandb.apis import public
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import Paginator, SizedPaginator
from wandb.errors.term import termlog
from wandb.proto.wandb_deprecated import Deprecated
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts._generated import (
    ARTIFACT_COLLECTION_MEMBERSHIP_FILES_GQL,
    ARTIFACT_VERSION_FILES_GQL,
    CREATE_ARTIFACT_COLLECTION_TAG_ASSIGNMENTS_GQL,
    DELETE_ARTIFACT_COLLECTION_TAG_ASSIGNMENTS_GQL,
    DELETE_ARTIFACT_PORTFOLIO_GQL,
    DELETE_ARTIFACT_SEQUENCE_GQL,
    MOVE_ARTIFACT_COLLECTION_GQL,
    PROJECT_ARTIFACT_COLLECTION_GQL,
    PROJECT_ARTIFACT_COLLECTIONS_GQL,
    PROJECT_ARTIFACT_TYPE_GQL,
    PROJECT_ARTIFACT_TYPES_GQL,
    PROJECT_ARTIFACTS_GQL,
    RUN_INPUT_ARTIFACTS_GQL,
    RUN_OUTPUT_ARTIFACTS_GQL,
    UPDATE_ARTIFACT_PORTFOLIO_GQL,
    UPDATE_ARTIFACT_SEQUENCE_GQL,
    ArtifactCollectionMembershipFiles,
    ArtifactCollectionsFragment,
    ArtifactsFragment,
    ArtifactTypeFragment,
    ArtifactTypesFragment,
    ArtifactVersionFiles,
    FilesFragment,
    ProjectArtifactCollection,
    ProjectArtifactCollections,
    ProjectArtifacts,
    ProjectArtifactType,
    ProjectArtifactTypes,
    RunInputArtifactConnectionFragment,
    RunOutputArtifactConnectionFragment,
)
from wandb.sdk.artifacts._gqlutils import omit_artifact_fields
from wandb.sdk.artifacts._validators import (
    SOURCE_ARTIFACT_COLLECTION_TYPE,
    FullArtifactPath,
    validate_artifact_name,
    validate_artifact_type,
)
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib import deprecate

from .utils import gql_compat

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact

    from . import RetryingClient, Run


class ArtifactTypes(Paginator["ArtifactType"]):
    """An lazy iterator of `ArtifactType` objects for a specific project.

    <!-- lazydoc-ignore-init: internal -->
    """

    QUERY = gql(PROJECT_ARTIFACT_TYPES_GQL)

    last_response: ArtifactTypesFragment | None

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        per_page: int = 50,
    ):
        self.entity = entity
        self.project = project

        variable_values = {
            "entityName": entity,
            "projectName": project,
        }
        super().__init__(client, variable_values, per_page)

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = ProjectArtifactTypes.model_validate(data)

        # Extract the inner `*Connection` result for faster/easier access.
        if not ((proj := result.project) and (conn := proj.artifact_types)):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = ArtifactTypesFragment.model_validate(conn)

    @property
    def _length(self) -> None:
        """Returns `None`.

        <!-- lazydoc-ignore: internal -->
        """
        # TODO
        return None

    @property
    def more(self) -> bool:
        """Returns whether there are more artifact types to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self) -> str | None:
        """Returns the cursor for the next page of results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return None
        return self.last_response.edges[-1].cursor

    def update_variables(self) -> None:
        """Update the cursor variable for pagination.

        <!-- lazydoc-ignore: internal -->
        """
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self) -> list[ArtifactType]:
        """Convert the raw response data into a list of ArtifactType objects.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return []

        return [
            ArtifactType(
                client=self.client,
                entity=self.entity,
                project=self.project,
                type_name=node.name,
                attrs=node.model_dump(exclude_unset=True),
            )
            for edge in self.last_response.edges
            if edge.node and (node := ArtifactTypeFragment.model_validate(edge.node))
        ]


class ArtifactType:
    """An artifact object that satisfies query based on the specified type.

    Args:
        client: The client instance to use for querying W&B.
        entity: The entity (user or team) that owns the project.
        project: The name of the project to query for artifact types.
        type_name: The name of the artifact type.
        attrs: Optional mapping of attributes to initialize the artifact type. If not provided,
            the object will load its attributes from W&B upon initialization.

    <!-- lazydoc-ignore-init: internal -->
    """

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        type_name: str,
        attrs: Mapping[str, Any] | None = None,
    ):
        self.client = client
        self.entity = entity
        self.project = project
        self.type = type_name
        self._attrs = attrs
        if self._attrs is None:
            self.load()

    def load(self) -> Mapping[str, Any]:
        """Load the artifact type attributes from W&B.

        <!-- lazydoc-ignore: internal -->
        """
        data: Mapping[str, Any] | None = self.client.execute(
            gql(PROJECT_ARTIFACT_TYPE_GQL),
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactTypeName": self.type,
            },
        )
        result = ProjectArtifactType.model_validate(data)
        if not ((proj := result.project) and (artifact_type := proj.artifact_type)):
            raise ValueError(f"Could not find artifact type {self.type}")

        self._attrs = artifact_type.model_dump(exclude_unset=True)
        return self._attrs

    @property
    def id(self) -> str:
        """The unique identifier of the artifact type."""
        return self._attrs["id"]

    @property
    def name(self) -> str:
        """The name of the artifact type."""
        return self._attrs["name"]

    @normalize_exceptions
    def collections(self, per_page: int = 50) -> ArtifactCollections:
        """Get all artifact collections associated with this artifact type.

        Args:
            per_page (int): The number of artifact collections to fetch per page.
                Default is 50.
        """
        return ArtifactCollections(self.client, self.entity, self.project, self.type)

    def collection(self, name: str) -> ArtifactCollection:
        """Get a specific artifact collection by name.

        Args:
            name (str): The name of the artifact collection to retrieve.
        """
        return ArtifactCollection(
            self.client, self.entity, self.project, name, self.type
        )

    def __repr__(self) -> str:
        return f"<ArtifactType {self.type}>"


class ArtifactCollections(SizedPaginator["ArtifactCollection"]):
    """Artifact collections of a specific type in a project.

    Args:
        client: The client instance to use for querying W&B.
        entity: The entity (user or team) that owns the project.
        project: The name of the project to query for artifact collections.
        type_name: The name of the artifact type for which to fetch collections.
        per_page: The number of artifact collections to fetch per page. Default is 50.

    <!-- lazydoc-ignore-init: internal -->
    """

    last_response: ArtifactCollectionsFragment | None

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        type_name: str,
        per_page: int = 50,
    ):
        self.entity = entity
        self.project = project
        self.type_name = type_name

        variable_values = {
            "entityName": entity,
            "projectName": project,
            "artifactTypeName": type_name,
        }

        if server_supports_artifact_collections_gql_edges(client):
            rename_fields = None
        else:
            rename_fields = {"artifactCollections": "artifactSequences"}

        self.QUERY = gql_compat(
            PROJECT_ARTIFACT_COLLECTIONS_GQL, rename_fields=rename_fields
        )

        super().__init__(client, variable_values, per_page)

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = ProjectArtifactCollections.model_validate(data)

        # Extract the inner `*Connection` result for faster/easier access.
        if not (
            (proj := result.project)
            and (type_ := proj.artifact_type)
            and (conn := type_.artifact_collections)
        ):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = ArtifactCollectionsFragment.model_validate(conn)

    @property
    def _length(self) -> int:
        """Returns the total number of artifact collections.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            self._load_page()
        return self.last_response.total_count

    @property
    def more(self):
        """Returns whether there are more artifacts to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self):
        """Returns the cursor for the next page of results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return None
        return self.last_response.edges[-1].cursor

    def update_variables(self) -> None:
        """Update the cursor variable for pagination.

        <!-- lazydoc-ignore: internal -->
        """
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self) -> list[ArtifactCollection]:
        """Convert the raw response data into a list of ArtifactCollection objects.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return []
        return [
            ArtifactCollection(
                client=self.client,
                entity=self.entity,
                project=self.project,
                name=node.name,
                type=self.type_name,
            )
            for edge in self.last_response.edges
            if (node := edge.node)
        ]


class ArtifactCollection:
    """An artifact collection that represents a group of related artifacts.

    Args:
        client: The client instance to use for querying W&B.
        entity: The entity (user or team) that owns the project.
        project: The name of the project to query for artifact collections.
        name: The name of the artifact collection.
        type: The type of the artifact collection (e.g., "dataset", "model").
        organization: Optional organization name if applicable.
        attrs: Optional mapping of attributes to initialize the artifact collection.
            If not provided, the object will load its attributes from W&B upon
            initialization.

    <!-- lazydoc-ignore-init: internal -->
    """

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        name: str,
        type: str,
        organization: str | None = None,
        attrs: Mapping[str, Any] | None = None,
        is_sequence: bool | None = None,
    ):
        self.client = client
        self.entity = entity
        self.project = project
        self._name = validate_artifact_name(name)
        self._saved_name = name
        self._type = type
        self._saved_type = type
        self._attrs = attrs
        if is_sequence is not None:
            self._is_sequence = is_sequence
        if (attrs is None) or (is_sequence is None):
            self.load()
        self._aliases = [a["node"]["alias"] for a in self._attrs["aliases"]["edges"]]
        self._description = self._attrs["description"]
        self._created_at = self._attrs["createdAt"]
        self._tags = [a["node"]["name"] for a in self._attrs["tags"]["edges"]]
        self._saved_tags = copy(self._tags)
        self.organization = organization

    @property
    def id(self) -> str:
        """The unique identifier of the artifact collection."""
        return self._attrs["id"]

    @normalize_exceptions
    def artifacts(self, per_page: int = 50) -> Artifacts:
        """Get all artifacts in the collection."""
        return Artifacts(
            client=self.client,
            entity=self.entity,
            project=self.project,
            collection_name=self._saved_name,
            type=self._saved_type,
            per_page=per_page,
        )

    @property
    def aliases(self) -> list[str]:
        """Artifact Collection Aliases."""
        return self._aliases

    @property
    def created_at(self) -> str:
        """The creation date of the artifact collection."""
        return self._created_at

    def load(self):
        """Load the artifact collection attributes from W&B.

        <!-- lazydoc-ignore: internal -->
        """
        if server_supports_artifact_collections_gql_edges(self.client):
            rename_fields = None
        else:
            rename_fields = {"artifactCollection": "artifactSequence"}

        response = self.client.execute(
            gql_compat(PROJECT_ARTIFACT_COLLECTION_GQL, rename_fields=rename_fields),
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactTypeName": self._saved_type,
                "artifactCollectionName": self._saved_name,
            },
        )

        result = ProjectArtifactCollection.model_validate(response)

        if not (
            result.project
            and (proj := result.project)
            and (type_ := proj.artifact_type)
            and (collection := type_.artifact_collection)
        ):
            raise ValueError(f"Could not find artifact type {self._saved_type}")

        sequence = type_.artifact_sequence
        self._is_sequence = (
            sequence is not None
        ) and sequence.typename__ == SOURCE_ARTIFACT_COLLECTION_TYPE

        if self._attrs is None:
            self._attrs = collection.model_dump(exclude_unset=True)
        return self._attrs

    @normalize_exceptions
    def change_type(self, new_type: str) -> None:
        """Deprecated, change type directly with `save` instead."""
        deprecate.deprecate(
            field_name=Deprecated.artifact_collection__change_type,
            warning_message="ArtifactCollection.change_type(type) is deprecated, use ArtifactCollection.save() instead.",
        )

        if self._saved_type != new_type:
            try:
                validate_artifact_type(self._saved_type, self.name)
            except ValueError as e:
                raise ValueError(
                    f"The current type '{self._saved_type!r}' is an internal type and cannot be changed."
                ) from e

        # Check that the new type is not going to conflict with internal types
        validate_artifact_type(new_type, self.name)

        if not self.is_sequence():
            raise ValueError("Artifact collection needs to be a sequence")
        termlog(
            f"Changing artifact collection type of {self._saved_type} to {new_type}"
        )
        self.client.execute(
            gql(MOVE_ARTIFACT_COLLECTION_GQL),
            variable_values={
                "artifactSequenceID": self.id,
                "destinationArtifactTypeName": new_type,
            },
        )
        self._saved_type = new_type
        self._type = new_type

    def is_sequence(self) -> bool:
        """Return whether the artifact collection is a sequence."""
        return self._is_sequence

    @normalize_exceptions
    def delete(self) -> None:
        """Delete the entire artifact collection."""
        self.client.execute(
            gql(
                DELETE_ARTIFACT_SEQUENCE_GQL
                if self.is_sequence()
                else DELETE_ARTIFACT_PORTFOLIO_GQL
            ),
            variable_values={"id": self.id},
        )

    @property
    def description(self) -> str:
        """A description of the artifact collection."""
        return self._description

    @description.setter
    def description(self, description: str | None) -> None:
        """Set the description of the artifact collection."""
        self._description = description

    @property
    def tags(self) -> list[str]:
        """The tags associated with the artifact collection."""
        return self._tags

    @tags.setter
    def tags(self, tags: list[str]) -> None:
        """Set the tags associated with the artifact collection."""
        if any(not re.match(r"^[-\w]+([ ]+[-\w]+)*$", tag) for tag in tags):
            raise ValueError(
                "Tags must only contain alphanumeric characters or underscores separated by spaces or hyphens"
            )
        self._tags = tags

    @property
    def name(self) -> str:
        """The name of the artifact collection."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        """Set the name of the artifact collection."""
        self._name = validate_artifact_name(name)

    @property
    def type(self):
        """Returns the type of the artifact collection."""
        return self._type

    @type.setter
    def type(self, type: list[str]) -> None:
        """Set the type of the artifact collection."""
        if not self.is_sequence():
            raise ValueError(
                "Type can only be changed if the artifact collection is a sequence."
            )
        self._type = type

    def _update_collection(self) -> None:
        self.client.execute(
            gql(
                UPDATE_ARTIFACT_SEQUENCE_GQL
                if self.is_sequence()
                else UPDATE_ARTIFACT_PORTFOLIO_GQL
            ),
            variable_values={
                "id": self.id,
                "name": self.name,
                "description": self.description,
            },
        )
        self._saved_name = self._name

    def _update_collection_type(self) -> None:
        self.client.execute(
            gql(MOVE_ARTIFACT_COLLECTION_GQL),
            variable_values={
                "artifactSequenceID": self.id,
                "destinationArtifactTypeName": self.type,
            },
        )
        self._saved_type = self._type

    def _add_tags(self, tags_to_add: Iterable[str]) -> None:
        self.client.execute(
            gql(CREATE_ARTIFACT_COLLECTION_TAG_ASSIGNMENTS_GQL),
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactCollectionName": self._saved_name,
                "tags": [{"tagName": tag} for tag in tags_to_add],
            },
        )

    def _delete_tags(self, tags_to_delete: Iterable[str]) -> None:
        self.client.execute(
            gql(DELETE_ARTIFACT_COLLECTION_TAG_ASSIGNMENTS_GQL),
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactCollectionName": self._saved_name,
                "tags": [{"tagName": tag} for tag in tags_to_delete],
            },
        )

    @normalize_exceptions
    def save(self) -> None:
        """Persist any changes made to the artifact collection."""
        if self._saved_type != self.type:
            try:
                validate_artifact_type(self.type, self._name)
            except ValueError as e:
                raise ValueError(f"Failed to save artifact collection: {e}") from e
            try:
                validate_artifact_type(self._saved_type, self._name)
            except ValueError as e:
                raise ValueError(
                    f"Failed to save artifact collection '{self._name}': "
                    f"The current type '{self._saved_type!r}' is an internal type and cannot be changed."
                ) from e

        self._update_collection()

        if self.is_sequence() and (self._saved_type != self._type):
            self._update_collection_type()

        current_tags = set(self._tags)
        saved_tags = set(self._saved_tags)
        if tags_to_add := (current_tags - saved_tags):
            self._add_tags(tags_to_add)
        if tags_to_delete := (saved_tags - current_tags):
            self._delete_tags(tags_to_delete)
        self._saved_tags = copy(self._tags)

    def __repr__(self) -> str:
        return f"<ArtifactCollection {self._name} ({self._type})>"


class Artifacts(SizedPaginator["Artifact"]):
    """An iterable collection of artifact versions associated with a project.

    Optionally pass in filters to narrow down the results based on specific criteria.

    Args:
        client: The client instance to use for querying W&B.
        entity: The entity (user or team) that owns the project.
        project: The name of the project to query for artifacts.
        collection_name: The name of the artifact collection to query.
        type: The type of the artifacts to query. Common examples include
            "dataset" or "model".
        filters: Optional mapping of filters to apply to the query.
        order: Optional string to specify the order of the results.
        per_page: The number of artifact versions to fetch per page. Default is 50.
        tags: Optional string or list of strings to filter artifacts by tags.

    <!-- lazydoc-ignore-init: internal -->
    """

    last_response: ArtifactsFragment | None

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        collection_name: str,
        type: str,
        filters: Mapping[str, Any] | None = None,
        order: str | None = None,
        per_page: int = 50,
        tags: str | list[str] | None = None,
    ):
        self.entity = entity
        self.collection_name = collection_name
        self.type = type
        self.project = project
        self.filters = {"state": "COMMITTED"} if filters is None else filters
        self.tags = [tags] if isinstance(tags, str) else tags
        self.order = order
        variables = {
            "project": self.project,
            "entity": self.entity,
            "order": self.order,
            "type": self.type,
            "collection": self.collection_name,
            "filters": json.dumps(self.filters),
        }

        if server_supports_artifact_collections_gql_edges(client):
            rename_fields = None
        else:
            rename_fields = {"artifactCollection": "artifactSequence"}

        self.QUERY = gql_compat(
            PROJECT_ARTIFACTS_GQL,
            omit_fields=omit_artifact_fields(client),
            rename_fields=rename_fields,
        )

        super().__init__(client, variables, per_page)

    @override
    def _update_response(self) -> None:
        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = ProjectArtifacts.model_validate(data)

        # Extract the inner `*Connection` result for faster/easier access.
        if not (
            (proj := result.project)
            and (type_ := proj.artifact_type)
            and (collection := type_.artifact_collection)
            and (conn := collection.artifacts)
        ):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = ArtifactsFragment.model_validate(conn)

    @property
    def _length(self) -> int:
        """Returns the total number of artifacts in the collection.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            self._load_page()
        return self.last_response.total_count

    @property
    def more(self) -> bool:
        """Returns whether there are more files to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self) -> str | None:
        """Returns the cursor for the next page of results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return None
        return self.last_response.edges[-1].cursor

    def convert_objects(self) -> list[Artifact]:
        """Convert the raw response data into a list of wandb.Artifact objects.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return []

        artifact_edges = (edge for edge in self.last_response.edges if edge.node)
        artifacts = (
            wandb.Artifact._from_attrs(
                path=FullArtifactPath(
                    prefix=self.entity,
                    project=self.project,
                    name=f"{self.collection_name}:{edge.version}",
                ),
                attrs=edge.node,
                client=self.client,
            )
            for edge in artifact_edges
        )
        required_tags = set(self.tags or [])
        return [art for art in artifacts if required_tags.issubset(art.tags)]


class RunArtifacts(SizedPaginator["Artifact"]):
    """An iterable collection of artifacts associated with a specific run.

    <!-- lazydoc-ignore-init: internal -->
    """

    last_response: (
        RunOutputArtifactConnectionFragment | RunInputArtifactConnectionFragment
    )

    #: The pydantic model used to parse the (inner part of the) raw response.
    _response_cls: type[
        RunOutputArtifactConnectionFragment | RunInputArtifactConnectionFragment
    ]

    def __init__(
        self,
        client: Client,
        run: Run,
        mode: Literal["logged", "used"] = "logged",
        per_page: int = 50,
    ):
        self.run = run

        if mode == "logged":
            self.run_key = "outputArtifacts"
            self.QUERY = gql_compat(
                RUN_OUTPUT_ARTIFACTS_GQL, omit_fields=omit_artifact_fields(client)
            )
            self._response_cls = RunOutputArtifactConnectionFragment
        elif mode == "used":
            self.run_key = "inputArtifacts"
            self.QUERY = gql_compat(
                RUN_INPUT_ARTIFACTS_GQL, omit_fields=omit_artifact_fields(client)
            )
            self._response_cls = RunInputArtifactConnectionFragment
        else:
            raise ValueError("mode must be logged or used")

        variable_values = {
            "entity": run.entity,
            "project": run.project,
            "runName": run.id,
        }
        super().__init__(client, variable_values, per_page)

    @override
    def _update_response(self) -> None:
        data = self.client.execute(self.QUERY, variable_values=self.variables)

        # Extract the inner `*Connection` result for faster/easier access.
        inner_data = data["project"]["run"][self.run_key]
        self.last_response = self._response_cls.model_validate(inner_data)

    @property
    def _length(self) -> int:
        """Returns the total number of artifacts in the collection.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            self._load_page()
        return self.last_response.total_count

    @property
    def more(self) -> bool:
        """Returns whether there are more artifacts to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self) -> str | None:
        """Returns the cursor for the next page of results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return None
        return self.last_response.edges[-1].cursor

    def convert_objects(self) -> list[Artifact]:
        """Convert the raw response data into a list of wandb.Artifact objects.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return []

        return [
            wandb.Artifact._from_attrs(
                path=FullArtifactPath(
                    prefix=proj.entity_name,
                    project=proj.name,
                    name=f"{artifact_seq.name}:v{node.version_index}",
                ),
                attrs=node,
                client=self.client,
            )
            for edge in self.last_response.edges
            if (node := edge.node)
            and (artifact_seq := node.artifact_sequence)
            and (proj := artifact_seq.project)
        ]


class ArtifactFiles(SizedPaginator["public.File"]):
    """A paginator for files in an artifact.

    <!-- lazydoc-ignore-init: internal -->
    """

    last_response: FilesFragment | None

    def __init__(
        self,
        client: Client,
        artifact: Artifact,
        names: Sequence[str] | None = None,
        per_page: int = 50,
    ):
        self.query_via_membership = InternalApi()._server_supports(
            ServerFeature.ARTIFACT_COLLECTION_MEMBERSHIP_FILES
        )
        self.artifact = artifact

        if self.query_via_membership:
            query_str = ARTIFACT_COLLECTION_MEMBERSHIP_FILES_GQL
            variables = {
                "entityName": artifact.entity,
                "projectName": artifact.project,
                "artifactName": artifact.name.split(":")[0],
                "artifactVersionIndex": artifact.version,
                "fileNames": names,
            }
        else:
            query_str = ARTIFACT_VERSION_FILES_GQL
            variables = {
                "entityName": artifact.source_entity,
                "projectName": artifact.source_project,
                "artifactName": artifact.source_name,
                "artifactTypeName": artifact.type,
                "fileNames": names,
            }

        # The server must advertise at least SDK 0.12.21
        # to get storagePath
        if not client.version_supported("0.12.21"):
            self.QUERY = gql_compat(query_str, omit_fields={"storagePath"})
        else:
            self.QUERY = gql(query_str)

        super().__init__(client, variables, per_page)

    @override
    def _update_response(self) -> None:
        data = self.client.execute(self.QUERY, variable_values=self.variables)

        # Extract the inner `*Connection` result for faster/easier access.
        if self.query_via_membership:
            result = ArtifactCollectionMembershipFiles.model_validate(data)
            conn = result.project.artifact_collection.artifact_membership.files
        else:
            result = ArtifactVersionFiles.model_validate(data)
            conn = result.project.artifact_type.artifact.files

        if conn is None:
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = FilesFragment.model_validate(conn)

    @property
    def path(self) -> list[str]:
        """Returns the path of the artifact."""
        return [self.artifact.entity, self.artifact.project, self.artifact.name]

    @property
    def _length(self) -> int:
        if self.last_response is None:
            self._load_page()
        """Returns the total number of files in the artifact.

        <!-- lazydoc-ignore: internal -->
        """
        return self.artifact.file_count

    @property
    def more(self) -> bool:
        """Returns whether there are more files to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self) -> str | None:
        """Returns the cursor for the next page of results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return None
        return self.last_response.edges[-1].cursor

    def update_variables(self) -> None:
        """Update the variables dictionary with the cursor.

        <!-- lazydoc-ignore: internal -->
        """
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self) -> list[public.File]:
        """Convert the raw response data into a list of public.File objects.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return []

        return [
            public.File(
                client=self.client,
                attrs=node.model_dump(exclude_unset=True),
            )
            for edge in self.last_response.edges
            if (node := edge.node)
        ]

    def __repr__(self) -> str:
        path_str = "/".join(self.path)
        return f"<ArtifactFiles {path_str} ({len(self)})>"


def server_supports_artifact_collections_gql_edges(
    client: RetryingClient, warn: bool = False
) -> bool:
    """Check if W&B server supports GraphQL edges for artifact collections.

    <!-- lazydoc-ignore-function: internal -->
    """
    # TODO: Validate this version
    # Edges were merged into core on Mar 2, 2022: https://github.com/wandb/core/commit/81c90b29eaacfe0a96dc1ebd83c53560ca763e8b
    # CLI version was bumped to "0.12.11" on Mar 3, 2022: https://github.com/wandb/core/commit/328396fa7c89a2178d510a1be9c0d4451f350d7b
    supported = client.version_supported("0.12.11")  # edges were merged on
    if not supported and warn:
        # First local release to include the above is 0.9.50: https://github.com/wandb/local/releases/tag/0.9.50
        wandb.termwarn(
            "W&B Local Server version does not support ArtifactCollection gql edges; falling back to using legacy ArtifactSequence. Please update server to at least version 0.9.50."
        )
    return supported
