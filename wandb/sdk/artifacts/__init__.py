from wandb.sdk.artifacts.local_artifact import Artifact as LocalArtifact
from wandb.sdk.artifacts.public_artifact import ARTIFACT_FRAGMENT
from wandb.sdk.artifacts.public_artifact import Artifact as PublicArtifact
from wandb.sdk.data_types._dtypes import Type, TypeRegistry


class _ArtifactVersionType(Type):
    name = "artifactVersion"
    types = [LocalArtifact, PublicArtifact]


TypeRegistry.add(_ArtifactVersionType)

__all__ = ["ARTIFACT_FRAGMENT"]
