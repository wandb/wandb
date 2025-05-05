"""Internal validation utilities that are specific to artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Literal, TypeVar, cast, overload

from wandb.sdk.artifacts._generated.fragments import (
    ArtifactPortfolioTypeFields,
    ArtifactSequenceTypeFields,
)
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

LINKED_ARTIFACT_COLLECTION_TYPE: Final[str] = ArtifactPortfolioTypeFields.model_fields[
    "typename__"
].default
SOURCE_ARTIFACT_COLLECTION_TYPE: Final[str] = ArtifactSequenceTypeFields.model_fields[
    "typename__"
].default


@dataclass
class _LinkArtifactFields:
    """Keep this list updated with fields where the linked artifact and the source artifact differ."""

    entity_name: str
    project_name: str
    name: str
    version: str
    aliases: list[str]

    # These fields shouldn't be set as they should always be
    # these values for a linked artifact
    # These fields shouldn't be set by the user as they should always be these values for a linked artifact
    _is_link: Literal[True] = field(init=False, default=True)
    _linked_artifacts: list[Artifact] = field(init=False, default_factory=list)

    @property
    def is_link(self) -> bool:
        return self._is_link

    @property
    def linked_artifacts(self) -> list[Artifact]:
        return self._linked_artifacts


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


INVALID_URL_CHARACTERS = ("/", "\\", "#", "?", "%", ":", "\r", "\n")


def validate_project_name(name: str) -> None:
    """Validates a project name according to W&B rules.

    Args:
        name: The project name string.

    Raises:
        ValueError: If the name is invalid (too long or contains invalid characters).
    """
    max_len = 128

    if len(name) == 0:
        raise ValueError("Project name cannot be empty")

    registry_name = ""
    if name.startswith(REGISTRY_PREFIX):
        registry_name = name[len(REGISTRY_PREFIX) :]
        if len(registry_name) == 0:
            raise ValueError("Registry name cannot be empty")

    if len(name) > max_len:
        if registry_name:
            raise ValueError(
                f"Invalid registry name {registry_name!r}, must be {max_len - len(REGISTRY_PREFIX)} characters or less"
            )
        else:
            raise ValueError(
                f"Invalid project name {name!r}, must be {max_len} characters or less"
            )

    # Find the first occurrence of any invalid character
    if invalid_chars := set(INVALID_URL_CHARACTERS).intersection(name):
        error_name = registry_name or name
        invalid_chars_repr = ", ".join(sorted(map(repr, invalid_chars)))
        raise ValueError(
            f"Invalid project/registry name {error_name!r}, cannot contain characters: {invalid_chars_repr!s}"
        )


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
