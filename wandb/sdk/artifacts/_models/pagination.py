"""Artifacts-specific data models for handling paginated results from GraphQL queries."""

from wandb._pydantic import Connection, ConnectionWithTotal

from .._generated.fragments import (
    ArtifactAliasFragment,
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
ArtifactCollectionConnection = ConnectionWithTotal[ArtifactCollectionFragment]
ProjectArtifactCollectionConnection = Connection[ArtifactCollectionFragment]
ArtifactMembershipConnection = Connection[ArtifactMembershipFragment]
ArtifactAliasConnection = Connection[ArtifactAliasFragment]

FileWithUrlConnection = Connection[FileWithUrlFragment]
ArtifactFileConnection = Connection[FileFragment]

RunArtifactConnection = ConnectionWithTotal[ArtifactFragment]

RegistryConnection = Connection[RegistryFragment]
RegistryCollectionConnection = ConnectionWithTotal[RegistryCollectionFragment]
