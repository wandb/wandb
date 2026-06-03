"""Artifacts-specific data models for handling paginated results from GraphQL queries."""

from typing import Annotated

from pydantic import AliasPath, Field

from wandb._pydantic import Connection, ConnectionWithTotal, GQLResult

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

ArtifactTypeConnection = Connection[ArtifactTypeFragment]


class ProjectArtifactTypesResult(GQLResult):
    connection: Annotated[
        ArtifactTypeConnection,
        Field(validation_alias=AliasPath("project", "artifactTypes")),
    ]


ArtifactCollectionConnection = ConnectionWithTotal[ArtifactCollectionFragment]


class ProjectArtifactTypeArtifactCollectionsResult(GQLResult):
    connection: Annotated[
        ArtifactCollectionConnection,
        Field(
            validation_alias=AliasPath("project", "artifactType", "artifactCollections")
        ),
    ]


ProjectArtifactCollectionConnection = Connection[ArtifactCollectionFragment]


class ProjectArtifactCollectionsResult(GQLResult):
    connection: Annotated[
        ProjectArtifactCollectionConnection,
        Field(validation_alias=AliasPath("project", "artifactCollections")),
    ]


ArtifactMembershipConnection = Connection[ArtifactMembershipFragment]

FileWithUrlConnection = Connection[FileWithUrlFragment]

ArtifactFileConnection = Connection[FileFragment]

RunArtifactConnection = ConnectionWithTotal[ArtifactFragment]

RegistryConnection = Connection[RegistryFragment]

RegistryCollectionConnection = ConnectionWithTotal[RegistryCollectionFragment]
