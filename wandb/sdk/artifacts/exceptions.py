"""Artifact exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from wandb import errors

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact


class ArtifactStatusError(AttributeError):
    """Raised when an artifact is in an invalid state for the requested operation."""

    def __init__(
        self,
        artifact: Artifact | None = None,
        attr: str | None = None,
        msg: str = "Artifact is in an invalid state for the requested operation.",
    ):
        cls_name = type(artifact).__name__ if artifact else "Artifact"
        method_id = f"{cls_name}.{attr}" if attr else cls_name
        formatted_msg = msg.format(artifact=artifact, method_id=method_id)

        # Follow the same pattern as AttributeError: `name/obj` properties set separately for
        # compatibility with Python < 3.10.
        super().__init__(formatted_msg)
        self.obj = artifact
        self.name = attr or ""


class ArtifactNotLoggedError(ArtifactStatusError):
    """Raised for Artifact methods or attributes only available after logging."""

    def __init__(self, artifact: Artifact | None = None, attr: str | None = None):
        super().__init__(
            artifact,
            attr,
            msg=(
                "{method_id!r} used prior to logging artifact or while in offline mode. "
                "Call wait() before accessing logged artifact properties."
            ),
        )


class ArtifactFinalizedError(ArtifactStatusError):
    """Raised for Artifact methods or attributes that can't be changed after logging."""

    def __init__(self, artifact: Artifact | None = None, attr: str | None = None):
        super().__init__(
            artifact,
            attr,
            msg="'{method_id}' used on logged artifact. Can't modify finalized artifact.",
        )


class WaitTimeoutError(errors.Error):
    """Raised when wait() timeout occurs before process is finished."""
