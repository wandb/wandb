"""Internal validation helper functions that are specific to artifacts."""

from __future__ import annotations

import re
import sys
from functools import wraps
from typing import TYPE_CHECKING, Callable, Hashable, TypeVar

if sys.version_info < (3, 10):
    from typing_extensions import Concatenate, ParamSpec
else:
    from typing import Concatenate, ParamSpec

from wandb.sdk.artifacts.exceptions import (
    ArtifactFinalizedError,
    ArtifactNotLoggedError,
)

if TYPE_CHECKING:
    from typing import Collection

    from wandb.sdk.artifacts.artifact import Artifact


HashableT = TypeVar("HashableT", bound=Hashable)


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


P = ParamSpec("P")
ReturnT = TypeVar("ReturnT")


def ensure_logged(
    method: Callable[Concatenate[Artifact, P], ReturnT],
) -> Callable[Concatenate[Artifact, P], ReturnT]:
    """Decorator to ensure that a method can only be called on logged artifacts."""
    attr_name = method.__name__

    @wraps(method)
    def wrapper(self: Artifact, *args: P.args, **kwargs: P.kwargs) -> ReturnT:
        if self.is_draft():
            raise ArtifactNotLoggedError(artifact=self, attr=attr_name)
        return method(self, *args, **kwargs)

    return wrapper


def ensure_not_finalized(
    method: Callable[Concatenate[Artifact, P], ReturnT],
) -> Callable[Concatenate[Artifact, P], ReturnT]:
    """Decorator to ensure that a method can only be called if the artifact has not been finalized."""
    attr_name = method.__name__

    @wraps(method)
    def wrapper(self: Artifact, *args: P.args, **kwargs: P.kwargs) -> None:
        if self._final:
            raise ArtifactFinalizedError(artifact=self, attr=attr_name)
        return method(self, *args, **kwargs)

    return wrapper
