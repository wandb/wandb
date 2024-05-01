"""Artifact exceptions."""

from typing import TYPE_CHECKING, Optional

from wandb import errors

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact


class ArtifactStatusError(AttributeError):
    """Raised when an artifact is in an invalid state for the requested operation."""

    def __init__(
        self,
        artifact: Optional["Artifact"] = None,
        attr: Optional[str] = None,
        msg: str = "Artifact is in an invalid state for the requested operation.",
    ):
        object_name = artifact.__class__.__name__ if artifact else "Artifact"
        method_id = f"{object_name}.{attr}" if attr else object_name
        super().__init__(msg.format(artifact=artifact, attr=attr, method_id=method_id))
        # Follow the same pattern as AttributeError.
        self.obj = artifact
        self.name = attr or ""


class ArtifactNotLoggedError(ArtifactStatusError):
    """Raised for Artifact methods or attributes only available after logging."""

    def __init__(
        self, artifact: Optional["Artifact"] = None, attr: Optional[str] = None
    ):
        super().__init__(
            artifact,
            attr,
            "'{method_id}' used prior to logging artifact or while in offline mode. "
            "Call wait() before accessing logged artifact properties.",
        )


class ArtifactFinalizedError(ArtifactStatusError):
    """Raised for Artifact methods or attributes that can't be changed after logging."""

    def __init__(
        self, artifact: Optional["Artifact"] = None, attr: Optional[str] = None
    ):
        super().__init__(
            artifact,
            attr,
            "'{method_id}' used on logged artifact. Can't modify finalized artifact.",
        )


class WaitTimeoutError(errors.Error):
    """Raised when wait() timeout occurs before process is finished."""
