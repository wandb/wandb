"""Artifact exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from wandb import errors

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact

    ArtifactT = TypeVar("ArtifactT", bound=Artifact)


class ArtifactStatusError(AttributeError):
    """Raised when an artifact is in an invalid state for the requested operation."""

    def __init__(
        self,
        msg: str = "Artifact is in an invalid state for the requested operation.",
        name: str | None = None,
        obj: ArtifactT | None = None,
    ):
        # Follow the same pattern as AttributeError in python 3.10+ by `name/obj` attributes
        # See: https://docs.python.org/3/library/exceptions.html#AttributeError
        try:
            super().__init__(msg, name=name, obj=obj)
        except TypeError:
            # The `name`/`obj` keyword args and attributes were only added in python >= 3.10
            super().__init__(msg)
            self.name = name or ""
            self.obj = obj


class ArtifactNotLoggedError(ArtifactStatusError):
    """Raised for Artifact methods or attributes only available after logging."""

    def __init__(self, fullname: str, obj: ArtifactT):
        *_, name = fullname.split(".")
        msg = (
            f"{fullname!r} used prior to logging artifact or while in offline mode. "
            f"Call {type(obj).wait.__qualname__}() before accessing logged artifact properties."
        )
        super().__init__(msg=msg, name=name, obj=obj)


class ArtifactFinalizedError(ArtifactStatusError):
    """Raised for Artifact methods or attributes that can't be changed after logging."""

    def __init__(self, fullname: str, obj: ArtifactT):
        *_, name = fullname.split(".")
        msg = f"{fullname!r} used on logged artifact. Can't modify finalized artifact."
        super().__init__(msg=msg, name=name, obj=obj)


class WaitTimeoutError(errors.Error):
    """Raised when wait() timeout occurs before process is finished."""
