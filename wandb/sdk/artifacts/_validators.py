"""Internal validation utilities that are specific to artifacts."""

from __future__ import annotations

import re
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

from wandb.sdk.artifacts.exceptions import (
    ArtifactFinalizedError,
    ArtifactNotLoggedError,
)

if TYPE_CHECKING:
    from typing import Collection

    from wandb.sdk.artifacts.artifact import Artifact

    ArtifactT = TypeVar("ArtifactT", bound=Artifact)


def validate_aliases(aliases: Collection[str]) -> list[str]:
    """Validate the artifact aliases and return them as a list.

    Raises:
        ValueError: If any of the aliases contain invalid characters.
    """
    invalid_chars = ("/", ":")
    if any(char in alias for alias in aliases for char in invalid_chars):
        raise ValueError(
            f"Aliases must not contain any of the following characters: {', '.join(invalid_chars)}"
        )
    return list(aliases)


_VALID_TAG_PATTERN: re.Pattern[str] = re.compile(r"^[-\w]+( +[-\w]+)*$")


def validate_tags(tags: Collection[str]) -> list[str]:
    """Validate the artifact tag names and return them as a deduped list.

    In the case of duplicates, only keep the first tag, and otherwise maintain the order of appearance.

    Raises:
        ValueError: If any of the tags contain invalid characters.
    """
    if any(not _VALID_TAG_PATTERN.match(tag) for tag in tags):
        raise ValueError(
            "Invalid tag(s).  "
            "Tags must only contain alphanumeric characters separated by hyphens, underscores, and/or spaces."
        )
    return list(dict.fromkeys(tags))


DecoratedF = TypeVar("DecoratedF", bound=Callable[..., Any])
"""Type hint for a decorated function that'll preserve its signature (e.g. for arg autocompletion in IDEs)."""


def ensure_logged(method: DecoratedF) -> DecoratedF:
    """Decorator to ensure that an Artifact method can only be called if the artifact has been logged.

    If the method is called on an artifact that's not logged, `ArtifactNotLoggedError` is raised.
    """
    # For clarity, use the qualified (full) name of the method
    method_fullname = method.__qualname__

    @wraps(method)
    def wrapper(self: ArtifactT, *args: Any, **kwargs: Any) -> Any:
        if self.is_draft():
            raise ArtifactNotLoggedError(fullname=method_fullname, obj=self)
        return method(self, *args, **kwargs)

    return cast(DecoratedF, wrapper)


def ensure_not_finalized(method: DecoratedF) -> DecoratedF:
    """Decorator to ensure that an `Artifact` method can only be called if the artifact isn't finalized.

    If the method is called on an artifact that's not logged, `ArtifactFinalizedError` is raised.
    """
    # For clarity, use the qualified (full) name of the method
    method_fullname = method.__qualname__

    @wraps(method)
    def wrapper(self: ArtifactT, *args: Any, **kwargs: Any) -> Any:
        if self._final:
            raise ArtifactFinalizedError(fullname=method_fullname, obj=self)
        return method(self, *args, **kwargs)

    return cast(DecoratedF, wrapper)
