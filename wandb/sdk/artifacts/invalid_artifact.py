"""Invalid artifact."""
from typing import TYPE_CHECKING, Any

from wandb.sdk.artifacts.exceptions import ArtifactNotLoggedError

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact as ArtifactInterface


class InvalidArtifact:
    """An "artifact" that raises an error when any properties are accessed."""

    def __init__(self, base_artifact: "ArtifactInterface"):
        super().__setattr__("base_artifact", base_artifact)

    def __getattr__(self, __name: str) -> Any:
        raise ArtifactNotLoggedError(artifact=self.base_artifact, attr=__name)

    def __setattr__(self, __name: str, __value: Any) -> None:
        raise ArtifactNotLoggedError(artifact=self.base_artifact, attr=__name)

    def __bool__(self) -> bool:
        return False
