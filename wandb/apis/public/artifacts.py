"""W&B Public API for Artifact objects.

This module provides classes for interacting with W&B artifacts and their
collections.
"""

from __future__ import annotations

from copy import copy
from functools import lru_cache
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Collection,
    Iterable,
    Literal,
    Sequence,
    TypeVar,
)

from typing_extensions import override
from wandb_gql import gql

from wandb._iterutils import always_list
from wandb._pydantic import Connection, ConnectionWithTotal
from wandb._strutils import nameof
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import RelayPaginator, SizedRelayPaginator
from wandb.errors.term import termlog
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto.wandb_telemetry_pb2 import Deprecated
from wandb.sdk.artifacts._models import ArtifactCollectionData
from wandb.sdk.lib.deprecation import warn_and_record_deprecation

from .files import File
from .utils import gql_compat

if TYPE_CHECKING:
    from wandb_graphql.language.ast import Document

    from wandb.apis.public.api import RetryingClient
    from wandb.sdk.artifacts._generated import (
        ArtifactAliasFragment,
        ArtifactCollectionFragment,
        ArtifactFragment,
        ArtifactMembershipFragment,
        ArtifactTypeFragment,
        FileFragment,
    )
    from wandb.sdk.artifacts._models.pagination import (
        ArtifactCollectionConnection,
        ArtifactFileConnection,
        ArtifactMembershipConnection,
        ArtifactTypeConnection,
    )
    from wandb.sdk.artifacts.artifact import Artifact

    from . import Run


TNode = TypeVar("TNode")


@lru_cache(maxsize=1)
def _run_artifacts_mode_to_gql() -> dict[Literal["logged", "used"], str]:
    """Lazily import and cache the run artifact GQL query strings.

    This keeps import-time light and only loads the generated GQL
    when RunArtifacts is actually used.
    """
    from wandb.sdk.artifacts._generated import (
        RUN_INPUT_ARTIFACTS_GQL,
        RUN_OUTPUT_ARTIFACTS_GQL,
    )

    return {"logged": RUN_OUTPUT_ARTIFACTS_GQL, "used": RUN_INPUT_ARTIFACTS_GQL}


class _ArtifactCollectionAliases(RelayPaginator["ArtifactAliasFragment", str]):
    """An internal iterator of collection alias names.

    <!-- lazydoc-ignore-init: internal -->
    """

    QUERY: ClassVar[Document | None] = None
    last_response: Connection[ArtifactAliasFragment] | None

    def __init__(
        self,
        client: RetryingClient,
        collection_id: str,
        per_page: int = 1_000,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import ARTIFACT_COLLECTION_ALIASES_GQL

            type(self).QUERY = gql(ARTIFACT_COLLECTION_ALIASES_GQL)

        variables = {"id": collection_id}
        super().__init__(client, variables=variables, per_page=per_page)

    def _update_response(self) -> None:
        from wandb.sdk.artifacts._generated import (
            ArtifactAliasFragment,
            ArtifactCollectionAliases,
        )

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = ArtifactCollectionAliases.model_validate(data)

        # Extract the inner `*Connection` result for faster/easier access.
        if not ((coll := result.artifact_collection) and (conn := coll.aliases)):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = Connection[ArtifactAliasFragment].model_validate(conn)

    def _convert(self, node: ArtifactAliasFragment) -> str:
        return node.alias


class ArtifactTypes(RelayPaginator["ArtifactTypeFragment", "ArtifactType"]):
    """An lazy iterator of `ArtifactType` objects for a specific project.

    <!-- lazydoc-ignore-init: internal -->
    """

    QUERY: ClassVar[Document | None] = None
    last_response: ArtifactTypeConnection | None

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        per_page: int = 50,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import PROJECT_ARTIFACT_TYPES_GQL

            type(self).QUERY = gql(PROJECT_ARTIFACT_TYPES_GQL)

        self.entity = entity
        self.project = project
        variables = {"entity": entity, "project": project}
        super().__init__(client, variables=variables, per_page=per_page)

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        from wandb.sdk.artifacts._generated import ProjectArtifactTypes
        from wandb.sdk.artifacts._models.pagination import ArtifactTypeConnection

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = ProjectArtifactTypes.model_validate(data)

        # Extract the inner `*Connection` result for faster/easier access.
        if not ((proj := result.project) and (conn := proj.artifact_types)):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = ArtifactTypeConnection.model_validate(conn)

    def _convert(self, node: ArtifactTypeFragment) -> ArtifactType:
        return ArtifactType(
            client=self.client,
            entity=self.entity,
            project=self.project,
            type_name=node.name,
            attrs=node,
        )


class ArtifactType:
    """An artifact object that satisfies query based on the specified type.

    Args:
        client: The client instance to use for querying W&B.
        entity: The entity (user or team) that owns the project.
        project: The name of the project to query for artifact types.
        type_name: The name of the artifact type.
        attrs: Optional attributes to initialize the ArtifactType.
            If omitted, the object will load its attributes from W&B upon
            initialization.

    <!-- lazydoc-ignore-init: internal -->
    """

    _attrs: ArtifactTypeFragment

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        type_name: str,
        attrs: ArtifactTypeFragment | None = None,
    ):
        from wandb.sdk.artifacts._generated import ArtifactTypeFragment

        self.client = client
        self.entity = entity
        self.project = project
        self.type = type_name

        # FIXME: Make this lazy, so we don't (re-)fetch the attributes until they are needed
        self._attrs = ArtifactTypeFragment.model_validate(attrs or self.load())

    def load(self) -> ArtifactTypeFragment:
        """Load the artifact type attributes from W&B.

        <!-- lazydoc-ignore: internal -->
        """
        from wandb.sdk.artifacts._generated import (
            PROJECT_ARTIFACT_TYPE_GQL,
            ArtifactTypeFragment,
            ProjectArtifactType,
        )

        gql_op = gql(PROJECT_ARTIFACT_TYPE_GQL)
        gql_vars = {"entity": self.entity, "project": self.project, "type": self.type}
        data = self.client.execute(gql_op, variable_values=gql_vars)
        result = ProjectArtifactType.model_validate(data)
        if not ((proj := result.project) and (artifact_type := proj.artifact_type)):
            raise ValueError(f"Could not find artifact type {self.type!r}")
        return ArtifactTypeFragment.model_validate(artifact_type)

    @property
    def id(self) -> str:
        """The unique identifier of the artifact type."""
        return self._attrs.id

    @property
    def name(self) -> str:
        """The name of the artifact type."""
        return self._attrs.name

    @normalize_exceptions
    def collections(self, per_page: int = 50) -> ArtifactCollections:
        """Get all artifact collections associated with this artifact type.

        Args:
            per_page (int): The number of artifact collections to fetch per page.
                Default is 50.
        """
        return ArtifactCollections(
            self.client,
            entity=self.entity,
            project=self.project,
            type_name=self.type,
        )

    def collection(self, name: str) -> ArtifactCollection:
        """Get a specific artifact collection by name.

        Args:
            name (str): The name of the artifact collection to retrieve.
        """
        return ArtifactCollection(
            self.client,
            entity=self.entity,
            project=self.project,
            name=name,
            type=self.type,
        )

    def __repr__(self) -> str:
        return f"<ArtifactType {self.type}>"


class ArtifactCollections(
    SizedRelayPaginator["ArtifactCollectionFragment", "ArtifactCollection"]
):
    """Artifact collections of a specific type in a project.

    Args:
        client: The client instance to use for querying W&B.
        entity: The entity (user or team) that owns the project.
        project: The name of the project to query for artifact collections.
        type_name: The name of the artifact type for which to fetch collections.
        per_page: The number of artifact collections to fetch per page. Default is 50.

    <!-- lazydoc-ignore-init: internal -->
    """

    QUERY: ClassVar[Document | None] = None
    last_response: ArtifactCollectionConnection | None

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        type_name: str,
        per_page: int = 50,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import PROJECT_ARTIFACT_COLLECTIONS_GQL

            type(self).QUERY = gql(PROJECT_ARTIFACT_COLLECTIONS_GQL)

        self.entity = entity
        self.project = project
        self.type_name = type_name
        variables = {"entity": entity, "project": project, "type": type_name}
        super().__init__(client, variables=variables, per_page=per_page)

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        from wandb.sdk.artifacts._generated import ProjectArtifactCollections
        from wandb.sdk.artifacts._models.pagination import ArtifactCollectionConnection

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = ProjectArtifactCollections.model_validate(data)

        # Extract the inner `*Connection` result for faster/easier access.
        if not (
            (proj := result.project)
            and (artifact_type := proj.artifact_type)
            and (conn := artifact_type.artifact_collections)
        ):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = ArtifactCollectionConnection.model_validate(conn)

    def _convert(self, node: ArtifactCollectionFragment) -> ArtifactCollection | None:
        if not node.project:
            return None
        return ArtifactCollection(
            client=self.client,
            entity=node.project.entity.name,
            project=node.project.name,
            name=node.name,
            type=node.type.name,
            attrs=node,
        )


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

    _saved: ArtifactCollectionData
    """The saved artifact collection data as last fetched from the W&B server."""

    _current: ArtifactCollectionData
    """The local, editable artifact collection data."""

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        name: str,
        type: str,
        organization: str | None = None,
        attrs: ArtifactCollectionFragment | None = None,
    ):
        self.client = client

        # FIXME: Make this lazy, so we don't (re-)fetch the attributes until they are needed
        self._update_data(attrs or self.load(entity, project, type, name))

        self.organization = organization

    def _update_data(self, fragment: ArtifactCollectionFragment) -> None:
        """Update the saved/current state of this collection with the given fragment.

        Can be used after receiving a GraphQL response with ArtifactCollection data.
        """
        # Separate "saved" vs "current" copies of the artifact collection data
        validated = ArtifactCollectionData.from_fragment(fragment)
        self._saved = validated
        self._current = validated.model_copy(deep=True)

    @property
    def id(self) -> str:
        """The unique identifier of the artifact collection."""
        return self._current.id

    @property
    def entity(self) -> str:
        """The entity (user or team) that owns the project."""
        return self._current.entity

    @property
    def project(self) -> str:
        """The project that contains the artifact collection."""
        return self._current.project

    @normalize_exceptions
    def artifacts(self, per_page: int = 50) -> Artifacts:
        """Get all artifacts in the collection."""
        return Artifacts(
            client=self.client,
            entity=self.entity,
            project=self.project,
            # Use the saved name and type, as they're mutable attributes
            # and may have been edited locally.
            collection_name=self._saved.name,
            type=self._saved.type,
            per_page=per_page,
        )

    @property
    def aliases(self) -> list[str]:
        """The aliases for all artifact versions contained in this collection."""
        if self._saved.aliases is None:
            aliases = list(
                _ArtifactCollectionAliases(self.client, collection_id=self.id)
            )
            self._saved = self._saved.model_copy(update={"aliases": aliases})
            self._current = self._current.model_copy(update={"aliases": aliases})

        return list(self._saved.aliases)

    @property
    def created_at(self) -> str:
        """The creation date of the artifact collection."""
        return self._saved.created_at

    def load(
        self, entity: str, project: str, type_: str, name: str
    ) -> ArtifactCollectionFragment:
        """Fetch and return the validated artifact collection data from W&B.

        <!-- lazydoc-ignore: internal -->
        """
        from wandb.sdk.artifacts._generated import (
            PROJECT_ARTIFACT_COLLECTION_GQL,
            ProjectArtifactCollection,
        )

        gql_op = gql(PROJECT_ARTIFACT_COLLECTION_GQL)
        gql_vars = {"entity": entity, "project": project, "type": type_, "name": name}
        data = self.client.execute(gql_op, variable_values=gql_vars)
        result = ProjectArtifactCollection.model_validate(data)
        if not (
            result.project
            and (proj := result.project)
            and (artifact_type := proj.artifact_type)
            and (collection := artifact_type.artifact_collection)
        ):
            raise ValueError(f"Could not find artifact type {type_!r}")
        return collection

    @normalize_exceptions
    def change_type(self, new_type: str) -> None:
        """Deprecated, change type directly with `save` instead."""
        from wandb.sdk.artifacts._generated import (
            UPDATE_ARTIFACT_SEQUENCE_TYPE_GQL,
            MoveArtifactSequenceInput,
        )
        from wandb.sdk.artifacts._validators import validate_artifact_type

        warn_and_record_deprecation(
            feature=Deprecated(artifact_collection__change_type=True),
            message="ArtifactCollection.change_type(type) is deprecated, use ArtifactCollection.save() instead.",
        )

        if (old_type := self._saved.type) != new_type:
            try:
                validate_artifact_type(old_type, self.name)
            except ValueError as e:
                raise ValueError(
                    f"The current type {old_type!r} is an internal type and cannot be changed."
                ) from e

        # Check that the new type is not going to conflict with internal types
        new_type = validate_artifact_type(new_type, self.name)

        if not self.is_sequence():
            raise ValueError("Artifact collection needs to be a sequence")

        termlog(f"Changing artifact collection type of {old_type!r} to {new_type!r}")

        gql_op = gql(UPDATE_ARTIFACT_SEQUENCE_TYPE_GQL)
        gql_input = MoveArtifactSequenceInput(
            artifact_sequence_id=self.id,
            destination_artifact_type_name=new_type,
        )
        self.client.execute(gql_op, variable_values={"input": gql_input.model_dump()})
        self._saved.type = new_type
        self._current.type = new_type

    def is_sequence(self) -> bool:
        """Return whether the artifact collection is a sequence."""
        return self._saved.is_sequence

    @normalize_exceptions
    def delete(self) -> None:
        """Delete the entire artifact collection."""
        from wandb.sdk.artifacts._generated import (
            DELETE_ARTIFACT_PORTFOLIO_GQL,
            DELETE_ARTIFACT_SEQUENCE_GQL,
        )

        gql_op = gql(
            DELETE_ARTIFACT_SEQUENCE_GQL
            if self.is_sequence()
            else DELETE_ARTIFACT_PORTFOLIO_GQL
        )
        self.client.execute(gql_op, variable_values={"id": self.id})

    @property
    def description(self) -> str | None:
        """A description of the artifact collection."""
        return self._current.description

    @description.setter
    def description(self, description: str | None) -> None:
        """Set the description of the artifact collection."""
        self._current.description = description

    @property
    def tags(self) -> list[str]:
        """The tags associated with the artifact collection."""
        return self._current.tags

    @tags.setter
    def tags(self, tags: Collection[str]) -> None:
        """Set the tags associated with the artifact collection."""
        self._current.tags = tags

    @property
    def name(self) -> str:
        """The name of the artifact collection."""
        return self._current.name

    @name.setter
    def name(self, name: str) -> None:
        """Set the name of the artifact collection."""
        self._current.name = name

    @property
    def type(self):
        """Returns the type of the artifact collection."""
        return self._current.type

    @type.setter
    def type(self, type: str) -> None:
        """Set the type of the artifact collection."""
        if not self.is_sequence():
            raise ValueError(
                "Type can only be changed if the artifact collection is a sequence."
            )
        self._current.type = type

    def _update_collection(self) -> None:
        from wandb.sdk.artifacts._generated import (
            UPDATE_ARTIFACT_PORTFOLIO_GQL,
            UPDATE_ARTIFACT_SEQUENCE_GQL,
            UpdateArtifactPortfolioInput,
            UpdateArtifactSequenceInput,
        )

        if self.is_sequence():
            gql_op = gql(UPDATE_ARTIFACT_SEQUENCE_GQL)
            gql_input = UpdateArtifactSequenceInput(
                artifact_sequence_id=self.id,
                name=self.name,
                description=self.description,
            )
        else:
            gql_op = gql(UPDATE_ARTIFACT_PORTFOLIO_GQL)
            gql_input = UpdateArtifactPortfolioInput(
                artifact_portfolio_id=self.id,
                name=self.name,
                description=self.description,
            )
        self.client.execute(gql_op, variable_values={"input": gql_input.model_dump()})
        self._saved.name = self._current.name
        self._saved.description = self._current.description

    def _update_sequence_type(self) -> None:
        from wandb.sdk.artifacts._generated import (
            UPDATE_ARTIFACT_SEQUENCE_TYPE_GQL,
            MoveArtifactSequenceInput,
        )

        gql_op = gql(UPDATE_ARTIFACT_SEQUENCE_TYPE_GQL)
        gql_input = MoveArtifactSequenceInput(
            artifact_sequence_id=self.id,
            destination_artifact_type_name=self.type,
        )
        self.client.execute(gql_op, variable_values={"input": gql_input.model_dump()})
        self._saved.type = self._current.type

    def _add_tags(self, tag_names: Iterable[str]) -> None:
        from wandb.sdk.artifacts._generated import (
            ADD_ARTIFACT_COLLECTION_TAGS_GQL,
            CreateArtifactCollectionTagAssignmentsInput,
        )

        gql_op = gql(ADD_ARTIFACT_COLLECTION_TAGS_GQL)
        gql_input = CreateArtifactCollectionTagAssignmentsInput(
            entity_name=self.entity,
            project_name=self.project,
            artifact_collection_name=self._saved.name,
            tags=[{"tagName": tag} for tag in tag_names],
        )
        self.client.execute(gql_op, variable_values={"input": gql_input.model_dump()})

    def _delete_tags(self, tag_names: Iterable[str]) -> None:
        from wandb.sdk.artifacts._generated import (
            DELETE_ARTIFACT_COLLECTION_TAGS_GQL,
            DeleteArtifactCollectionTagAssignmentsInput,
        )

        gql_op = gql(DELETE_ARTIFACT_COLLECTION_TAGS_GQL)
        gql_input = DeleteArtifactCollectionTagAssignmentsInput(
            entity_name=self.entity,
            project_name=self.project,
            artifact_collection_name=self._saved.name,
            tags=[{"tagName": tag} for tag in tag_names],
        )
        self.client.execute(gql_op, variable_values={"input": gql_input.model_dump()})

    @normalize_exceptions
    def save(self) -> None:
        """Persist any changes made to the artifact collection."""
        from wandb.sdk.artifacts._validators import validate_artifact_type

        if (old_type := self._saved.type) != (new_type := self.type):
            try:
                validate_artifact_type(new_type, self.name)
            except ValueError as e:
                reason = str(e)
                raise ValueError(
                    f"Failed to save artifact collection {self.name!r}: {reason}"
                ) from e
            try:
                validate_artifact_type(old_type, self.name)
            except ValueError as e:
                reason = f"The current type {old_type!r} is an internal type and cannot be changed."
                raise ValueError(
                    f"Failed to save artifact collection {self.name!r}: {reason}"
                ) from e

        # FIXME: Consider consolidating the multiple GQL mutations into a single call.
        self._update_collection()

        if self.is_sequence() and (old_type != new_type):
            self._update_sequence_type()

        if (new_tags := set(self._current.tags)) != (old_tags := set(self._saved.tags)):
            if added_tags := (new_tags - old_tags):
                self._add_tags(added_tags)
            if deleted_tags := (old_tags - new_tags):
                self._delete_tags(deleted_tags)
            self._saved.tags = copy(new_tags)

    def __repr__(self) -> str:
        return f"<ArtifactCollection {self.name} ({self.type})>"


class Artifacts(SizedRelayPaginator["ArtifactMembershipFragment", "Artifact"]):
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

    QUERY: Document  # Must be set per-instance

    # Loosely-annotated to avoid importing heavy types at module import time.
    last_response: ArtifactMembershipConnection | None

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        collection_name: str,
        type: str,
        *,
        per_page: int = 50,
        tags: str | list[str] | None = None,
    ):
        from wandb.sdk.artifacts._generated import PROJECT_ARTIFACTS_GQL

        self.QUERY = gql(PROJECT_ARTIFACTS_GQL)

        self.entity = entity
        self.collection_name = collection_name
        self.type = type
        self.project = project
        self.tags = always_list(tags or [])
        variables = {
            "entity": self.entity,
            "project": self.project,
            "type": self.type,
            "collection": self.collection_name,
        }
        super().__init__(client, variables=variables, per_page=per_page)

    @override
    def _update_response(self) -> None:
        from wandb.sdk.artifacts._generated import ProjectArtifacts
        from wandb.sdk.artifacts._models.pagination import ArtifactMembershipConnection

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = ProjectArtifacts.model_validate(data)

        # Extract the inner `*Connection` result for faster/easier access.
        if not (
            (proj := result.project)
            and (type_ := proj.artifact_type)
            and (collection := type_.artifact_collection)
            and (conn := collection.artifact_memberships)
        ):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = ArtifactMembershipConnection.model_validate(conn)

    @override
    def _convert(self, node: ArtifactMembershipFragment) -> Artifact | None:
        from wandb.sdk.artifacts._validators import FullArtifactPath
        from wandb.sdk.artifacts.artifact import Artifact

        if not (
            (collection := node.artifact_collection)
            and (project := collection.project)
            and node.artifact
            and (version_idx := node.version_index) is not None
        ):
            return None

        return Artifact._from_membership(
            membership=node,
            target=FullArtifactPath(
                prefix=project.entity.name,
                project=project.name,
                name=f"{collection.name}:v{version_idx}",
            ),
            client=self.client,
        )

    @override
    def convert_objects(self) -> list[Artifact]:
        """Convert the raw response data into a list of wandb.Artifact objects.

        <!-- lazydoc-ignore: internal -->
        """
        if not (artifacts := super().convert_objects()):
            return []
        # parent method is overridden to maintain this prior client-side tag filtering logic
        required_tags = set(self.tags or [])
        return [art for art in artifacts if required_tags.issubset(art.tags)]


class RunArtifacts(SizedRelayPaginator["ArtifactFragment", "Artifact"]):
    """An iterable collection of artifacts associated with a specific run.

    <!-- lazydoc-ignore-init: internal -->
    """

    QUERY: Document  # Must be set per-instance
    last_response: ConnectionWithTotal[ArtifactFragment] | None

    def __init__(
        self,
        client: RetryingClient,
        run: Run,
        mode: Literal["logged", "used"] = "logged",
        per_page: int = 50,
    ):
        try:
            query_str = _run_artifacts_mode_to_gql()[mode]
        except LookupError:
            raise ValueError("mode must be logged or used")
        else:
            self.QUERY = gql(query_str)

        self.run = run
        variables = {"entity": run.entity, "project": run.project, "run": run.id}
        super().__init__(client, variables=variables, per_page=per_page)

    @override
    def _update_response(self) -> None:
        from wandb.sdk.artifacts._models.pagination import RunArtifactConnection

        data = self.client.execute(self.QUERY, variable_values=self.variables)

        # Extract the inner `*Connection` result for faster/easier access.
        inner_data = data["project"]["run"]["artifacts"]
        self.last_response = RunArtifactConnection.model_validate(inner_data)

    def _convert(self, node: ArtifactFragment) -> Artifact | None:
        from wandb.sdk.artifacts._validators import FullArtifactPath
        from wandb.sdk.artifacts.artifact import Artifact

        if node.artifact_sequence.project is None:
            return None
        return Artifact._from_attrs(
            path=FullArtifactPath(
                prefix=node.artifact_sequence.project.entity.name,
                project=node.artifact_sequence.project.name,
                name=f"{node.artifact_sequence.name}:v{node.version_index}",
            ),
            src_art=node,
            client=self.client,
        )


class ArtifactFiles(SizedRelayPaginator["FileFragment", "File"]):
    """A paginator for files in an artifact.

    <!-- lazydoc-ignore-init: internal -->
    """

    QUERY: Document  # Must be set per-instance
    last_response: ArtifactFileConnection | None

    def __init__(
        self,
        client: RetryingClient,
        artifact: Artifact,
        names: Sequence[str] | None = None,
        per_page: int = 50,
    ):
        from wandb.sdk.artifacts._generated import (
            GET_ARTIFACT_FILES_GQL,
            GET_ARTIFACT_MEMBERSHIP_FILES_GQL,
        )
        from wandb.sdk.artifacts._gqlutils import server_supports

        self.query_via_membership = server_supports(
            client, pb.ARTIFACT_COLLECTION_MEMBERSHIP_FILES
        )
        self.artifact = artifact

        if self.query_via_membership:
            query_str = GET_ARTIFACT_MEMBERSHIP_FILES_GQL
            variables = {
                "entity": artifact.entity,
                "project": artifact.project,
                "collection": artifact.name.split(":")[0],
                "alias": artifact.version,
                "fileNames": names,
            }
        else:
            query_str = GET_ARTIFACT_FILES_GQL
            variables = {
                "entity": artifact.source_entity,
                "project": artifact.source_project,
                "name": artifact.source_name,
                "type": artifact.type,
                "fileNames": names,
            }

        omit_fields = (
            None
            if server_supports(client, pb.TOTAL_COUNT_IN_FILE_CONNECTION)
            else {"totalCount"}
        )
        self.QUERY = gql_compat(query_str, omit_fields=omit_fields)
        super().__init__(client, variables=variables, per_page=per_page)

    @override
    def _update_response(self) -> None:
        from wandb.sdk.artifacts._generated import (
            GetArtifactFiles,
            GetArtifactMembershipFiles,
        )
        from wandb.sdk.artifacts._models.pagination import ArtifactFileConnection

        data = self.client.execute(self.QUERY, variable_values=self.variables)

        # Extract the inner `*Connection` result for faster/easier access.
        if self.query_via_membership:
            result = GetArtifactMembershipFiles.model_validate(data)
            conn = result.project.artifact_collection.artifact_membership.files
        else:
            result = GetArtifactFiles.model_validate(data)
            conn = result.project.artifact_type.artifact.files

        if conn is None:
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = ArtifactFileConnection.model_validate(conn)

    @property
    def path(self) -> list[str]:
        """Returns the path of the artifact."""
        return [self.artifact.entity, self.artifact.project, self.artifact.name]

    def _convert(self, node: FileFragment) -> File:
        return File(self.client, attrs=node.model_dump(exclude_unset=True))

    def __repr__(self) -> str:
        path_str = "/".join(self.path)
        try:
            total = len(self)
        except NotImplementedError:
            # Older server versions don't correctly support totalCount
            return f"<ArtifactFiles {path_str}>"
        else:
            return f"<ArtifactFiles {path_str} ({total})>"
