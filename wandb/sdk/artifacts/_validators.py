"""Internal validation utilities that are specific to artifacts."""

from __future__ import annotations

import re
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast, overload

from wandb.sdk.artifacts.exceptions import (
    ArtifactFinalizedError,
    ArtifactNotLoggedError,
)

if TYPE_CHECKING:
    from typing import Collection, Final, Iterable, Union

    from wandb.sdk.artifacts.artifact import Artifact

    ArtifactT = TypeVar("ArtifactT", bound=Artifact)
    T = TypeVar("T")
    ClassInfo = Union[type[T], tuple[type[T], ...]]


REGISTRY_PREFIX: Final[str] = "wandb-registry-"
MAX_ARTIFACT_METADATA_KEYS: Final[int] = 100

ARTIFACT_NAME_MAXLEN: Final[int] = 128
ARTIFACT_NAME_INVALID_CHARS: Final[frozenset[str]] = frozenset({"/"})


# For mypy checks
@overload
def always_list(obj: Iterable[T], base_type: ClassInfo = ...) -> list[T]: ...
@overload
def always_list(obj: T, base_type: ClassInfo = ...) -> list[T]: ...


def always_list(obj: Any, base_type: Any = (str, bytes)) -> list[T]:
    """Return a guaranteed list of objects from a single instance OR iterable of such objects.

    By default, assume the returned list should have string-like elements (i.e. `str`/`bytes`).

    Adapted from `more_itertools.always_iterable`, but simplified for internal use.  See:
    https://more-itertools.readthedocs.io/en/stable/api.html#more_itertools.always_iterable
    """
    return [obj] if isinstance(obj, base_type) else list(obj)


def validate_artifact_name(name: str) -> str:
    """Validate the artifact name, returning it if successful.

    Raises:
        ValueError: If the artifact name is invalid.
    """
    if len(name) > ARTIFACT_NAME_MAXLEN:
        short_name = f"{name[:ARTIFACT_NAME_MAXLEN]} ..."
        raise ValueError(
            f"Artifact name is longer than {ARTIFACT_NAME_MAXLEN} characters: {short_name!r}"
        )

    if ARTIFACT_NAME_INVALID_CHARS.intersection(name):
        raise ValueError(
            "Artifact names must not contain any of the following characters: "
            f"{', '.join(sorted(ARTIFACT_NAME_INVALID_CHARS))}.  Got: {name!r}"
        )

    return name


def validate_aliases(aliases: Collection[str] | str) -> list[str]:
    """Validate the artifact aliases and return them as a list.

    Raises:
        ValueError: If any of the aliases contain invalid characters.
    """
    aliases_list = always_list(aliases)

    invalid_chars = ("/", ":")
    if any(char in alias for alias in aliases_list for char in invalid_chars):
        raise ValueError(
            f"Aliases must not contain any of the following characters: {', '.join(invalid_chars)}"
        )
    return aliases_list


def validate_artifact_types_list(artifact_types: list[str]) -> list[str]:
    """Return True if the artifact types list is valid, False otherwise."""
    artifact_types = always_list(artifact_types)
    invalid_chars = ("/", ":")
    if any(
        char in type or len(type) > 128
        for type in artifact_types
        for char in invalid_chars
    ):
        raise ValueError(
            f"""Artifact types must not contain any of the following characters: {", ".join(invalid_chars)}
              and must be less than equal to 128 characters"""
        )
    return artifact_types


_VALID_TAG_PATTERN: re.Pattern[str] = re.compile(r"^[-\w]+( +[-\w]+)*$")


def validate_tags(tags: Collection[str] | str) -> list[str]:
    """Validate the artifact tag names and return them as a deduped list.

    In the case of duplicates, only keep the first tag, and otherwise maintain the order of appearance.

    Raises:
        ValueError: If any of the tags contain invalid characters.
    """
    tags_list = always_list(tags)

    if any(not _VALID_TAG_PATTERN.match(tag) for tag in tags_list):
        raise ValueError(
            "Invalid tag(s).  "
            "Tags must only contain alphanumeric characters separated by hyphens, underscores, and/or spaces."
        )
    return list(dict.fromkeys(tags_list))


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


def is_artifact_registry_project(project: str) -> bool:
    return project.startswith(REGISTRY_PREFIX)
