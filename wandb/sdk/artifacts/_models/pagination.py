"""Artifacts-specific data models for handling paginated results from GraphQL queries."""

from typing import Annotated

from pydantic import AliasPath, Field

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


class ProjectArtifactTypesResult(GQLResult):
    connection: Annotated[
        Connection[ArtifactTypeFragment],
        Field(validation_alias=AliasPath("project", "artifactTypes")),
    ]


class ProjectArtifactTypeArtifactCollectionsResult(GQLResult):
    connection: Annotated[
        ConnectionWithTotal[ArtifactCollectionFragment],
        Field(
            validation_alias=AliasPath("project", "artifactType", "artifactCollections")
        ),
    ]


class ProjectArtifactCollectionsResult(GQLResult):
    connection: Annotated[
        Connection[ArtifactCollectionFragment],
        Field(validation_alias=AliasPath("project", "artifactCollections")),
    ]


class VersionedArtifactEdge(Edge[ArtifactFragment]):
    # The artifact `version` is read from the GraphQL edge, not the node.
    version: str


class ProjectArtifactConnection(ConnectionWithTotal[ArtifactFragment]):
    edges: list[VersionedArtifactEdge]


class ProjectArtifactsResult(GQLResult):
    connection: Annotated[
        ProjectArtifactConnection,
        Field(
            validation_alias=AliasPath(
                "project", "artifactType", "artifactCollection", "artifacts"
            )
        ),
    ]


ArtifactMembershipConnection = Connection[ArtifactMembershipFragment]

FileWithUrlConnection = Connection[FileWithUrlFragment]

ArtifactFileConnection = Connection[FileFragment]


class ProjectArtifactFilesResult(GQLResult):
    connection: Annotated[
        ArtifactFileConnection,
        Field(
            validation_alias=AliasPath("project", "artifactType", "artifact", "files")
        ),
    ]


class ProjectArtifactMembershipFilesResult(GQLResult):
    connection: Annotated[
        ArtifactFileConnection,
        Field(
            validation_alias=AliasPath(
                "project", "artifactCollection", "artifactMembership", "files"
            )
        ),
    ]


RunArtifactConnection = ConnectionWithTotal[ArtifactFragment]

RegistryConnection = Connection[RegistryFragment]

RegistryCollectionConnection = ConnectionWithTotal[RegistryCollectionFragment]
