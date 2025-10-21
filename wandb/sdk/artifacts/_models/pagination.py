"""Artifacts-specific data models for handling paginated results from GraphQL queries."""

from wandb._pydantic import Connection, ConnectionWithTotal

from .._generated import (
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

ArtifactAliasConnection = Connection[ArtifactAliasFragment]
ArtifactTypeConnection = Connection[ArtifactTypeFragment]
ArtifactCollectionConnection = ConnectionWithTotal[ArtifactCollectionFragment]
ArtifactMembershipConnection = Connection[ArtifactMembershipFragment]

FileWithUrlConnection = Connection[FileWithUrlFragment]
ArtifactFileConnection = Connection[FileFragment]

RunArtifactConnection = ConnectionWithTotal[ArtifactFragment]

RegistryConnection = Connection[RegistryFragment]
RegistryCollectionConnection = ConnectionWithTotal[RegistryCollectionFragment]
