"""Artifacts-specific data models for handling paginated results from GraphQL queries."""

from typing import Annotated, TypeVar

from pydantic import AliasPath, Field
from pydantic.fields import FieldInfo

from wandb._pydantic import Connection, ConnectionWithTotal, Edge, GQLResult

from .._generated.fragments import (
    ArtifactCollectionFragment,
    ArtifactFragment,
    ArtifactMembershipFragment,
    ArtifactTypeFragment,
    FileFragment,
    FileWithUrlFragment,
    RegistryCollectionFragment,
    RegistryFragment,
)

NodeT = TypeVar("NodeT")


def GQLPath(first_arg: str, *args: str | int) -> FieldInfo:  # noqa: N802
    """Create Pydantic field metadata for a nested GraphQL response path."""
    return Field(validation_alias=AliasPath(first_arg, *args))


# An intermediate `null` in an `AliasPath` leaves the root response in the
# validation error's `input`; a terminal `null` has `input=None` and the path in `loc`.


class ProjectArtifactTypesResult(GQLResult):
    connection: Annotated[
        Connection[ArtifactTypeFragment],
        GQLPath("project", "artifactTypes"),
    ]


class ProjectArtifactTypeArtifactCollectionsResult(GQLResult):
    connection: Annotated[
        ConnectionWithTotal[ArtifactCollectionFragment],
        GQLPath("project", "artifactType", "artifactCollections"),
    ]


class ProjectArtifactCollectionsResult(GQLResult):
    connection: Annotated[
        Connection[ArtifactCollectionFragment],
        GQLPath("project", "artifactCollections"),
    ]


class _VersionedEdge(Edge[NodeT]):
    version: str  # The artifact `version` is on the GraphQL edge, not node.


class ProjectArtifactConnection(ConnectionWithTotal[NodeT]):
    edges: list[_VersionedEdge[ArtifactFragment]]  # type: ignore[assignment]


class ProjectArtifactsResult(GQLResult):
    connection: Annotated[
        ProjectArtifactConnection,
        GQLPath("project", "artifactType", "artifactCollection", "artifacts"),
    ]


ArtifactMembershipConnection = Connection[ArtifactMembershipFragment]

FileWithUrlConnection = Connection[FileWithUrlFragment]


class ProjectArtifactMembershipFilesResult(GQLResult):
    connection: Annotated[
        Connection[FileFragment],
        GQLPath("project", "artifactCollection", "artifactMembership", "files"),
    ]


RunArtifactConnection = ConnectionWithTotal[ArtifactFragment]

RegistryConnection = Connection[RegistryFragment]

RegistryCollectionConnection = ConnectionWithTotal[RegistryCollectionFragment]
