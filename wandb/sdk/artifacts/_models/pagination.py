"""Artifacts-specific data models for handling paginated results from GraphQL queries."""

from wandb._pydantic import Connection, ConnectionWithOptionalTotal, ConnectionWithTotal

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
ArtifactCollectionConnection = ConnectionWithTotal[ArtifactCollectionFragment]
ArtifactMembershipConnection = Connection[ArtifactMembershipFragment]

FileWithUrlConnection = Connection[FileWithUrlFragment]
ArtifactFileConnection = ConnectionWithOptionalTotal[FileFragment]

RunArtifactConnection = ConnectionWithTotal[ArtifactFragment]

RegistryConnection = Connection[RegistryFragment]
RegistryCollectionConnection = ConnectionWithTotal[RegistryCollectionFragment]
