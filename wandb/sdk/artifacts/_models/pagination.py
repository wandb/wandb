"""Artifacts-specific data models for handling paginated results from GraphQL queries."""

from wandb._pydantic import Connection, ConnectionWithTotal

from .._generated.fragments import (
    ArtifactFragment,
    ArtifactTypeFragment,
    FileFragment,
    FileWithUrlFragment,
)

ArtifactTypeConnection = Connection[ArtifactTypeFragment]

FileWithUrlConnection = Connection[FileWithUrlFragment]
ArtifactFileConnection = Connection[FileFragment]

RunArtifactConnection = ConnectionWithTotal[ArtifactFragment]
