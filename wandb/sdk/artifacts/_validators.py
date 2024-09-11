"""Internal validation helper functions that are specific to artifacts."""

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


DecoratedFunc = TypeVar("DecoratedFunc", bound=Callable[..., Any])


def ensure_logged(method: DecoratedFunc) -> DecoratedFunc:
    """Decorator to ensure that a method can only be called on logged artifacts."""
    attr_name = method.__name__

    @wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        self: Artifact = args[0]
        if self.is_draft():
            raise ArtifactNotLoggedError(artifact=self, attr=attr_name)
        return method(*args, **kwargs)

    return cast(DecoratedFunc, wrapper)


def ensure_not_finalized(method: DecoratedFunc) -> DecoratedFunc:
    """Decorator to ensure that a method can only be called if the artifact has not been finalized."""
    attr_name = method.__name__

    @wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        self: Artifact = args[0]
        if self._final:
            raise ArtifactFinalizedError(artifact=self, attr=attr_name)
        return method(*args, **kwargs)

    return cast(DecoratedFunc, wrapper)
