"""Internal validation utilities that are specific to artifacts."""

from __future__ import annotations

import re
from dataclasses import astuple, dataclass, field, replace
from functools import wraps
from textwrap import shorten
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Optional, TypeVar, cast

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Self

from wandb._iterutils import always_list
from wandb._pydantic import from_json, gql_typename, to_json
from wandb.util import json_friendly_val

from ._generated import ArtifactPortfolioTypeFields, ArtifactSequenceTypeFields
from .exceptions import ArtifactFinalizedError, ArtifactNotLoggedError

if TYPE_CHECKING:
    from typing import Collection, Final

    from wandb.sdk.artifacts.artifact import Artifact

    ArtifactT = TypeVar("ArtifactT", bound=Artifact)
    T = TypeVar("T")


REGISTRY_PREFIX: Final[str] = "wandb-registry-"
REGISTRY_PREFIX_LEN: Final[int] = len(REGISTRY_PREFIX)

MAX_ARTIFACT_METADATA_KEYS: Final[int] = 100

MAX_NAME_LEN: Final[int] = 128
"""The default maximum length for most W&B names, unless otherwise specified (or ignored)."""


LINKED_ARTIFACT_COLLECTION_TYPE: Final[str] = gql_typename(ArtifactPortfolioTypeFields)
SOURCE_ARTIFACT_COLLECTION_TYPE: Final[str] = gql_typename(ArtifactSequenceTypeFields)


@dataclass
class LinkArtifactFields:
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


INVALID_ARTIFACT_CHARS: Final[frozenset[str]] = frozenset("/:")
"""Invalid characters for artifact names or other components of an artifact path."""

VALID_ARTIFACT_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_\-.]+$")
"""Regex pattern for validating artifact names."""


def truncate(name: str, max_len: int) -> str:
    """Truncates a string to avoid long error messages."""
    # Add some extra buffer, partly to account for the ellipsis
    return shorten(name, width=max_len + 5, placeholder="...")


def join_reprs(items: Collection[str]) -> str:
    """Returns an ordered representation of the given characters for inline display."""
    return ", ".join(sorted(map(repr, items)))


def validate_artifact_name(name: str) -> str:
    """Validate an artifact name, returning it if successful.

    Raises:
        ValueError: If the artifact name is invalid.
    """
    if len(name) > MAX_NAME_LEN:
        raise ValueError(
            f"Artifact name is longer than {MAX_NAME_LEN} characters: {truncate(name, MAX_NAME_LEN)!r}"
        )

    # Note: This check was absorbed from `Artifact.__init__` as of 2025-07-28.
    # If this check causes issues here, remove it and restore it to
    # its original position at the top of `Artifact.__init__`.
    if not VALID_ARTIFACT_PATTERN.match(name):
        raise ValueError(
            f"Artifact names may only contain alphanumeric characters, dashes, "
            f"underscores, and dots. Invalid name: {name!r}"
        )

    if INVALID_ARTIFACT_CHARS.intersection(name):
        raise ValueError(
            "Artifact names must not contain any of the following characters: "
            f"{join_reprs(INVALID_ARTIFACT_CHARS)}.  Got: {name!r}"
        )

    return name


INVALID_URL_CHARS: Final[frozenset[str]] = frozenset("/\\#?%:\r\n")
"""Invalid characters for project/registry names."""


def validate_project_name(name: str) -> None:
    """Validates a project name according to W&B rules.

    Args:
        name: The project name string.

    Raises:
        ValueError: If the name is invalid (too long or contains invalid characters).
    """
    if not name:
        raise ValueError("Project name cannot be empty")

    if name == REGISTRY_PREFIX:
        raise ValueError("Registry name cannot be empty")

    if is_artifact_registry_project(name):
        validated_name = name[REGISTRY_PREFIX_LEN:]
        max_len = MAX_NAME_LEN - REGISTRY_PREFIX_LEN
        name_type = "registry"
    else:
        validated_name = name
        max_len = MAX_NAME_LEN
        name_type = "project"

    if len(validated_name) > max_len:
        raise ValueError(
            f"Invalid {name_type!s} name {truncate(validated_name, max_len)!r}, must be {max_len!r} characters or less"
        )

    # Find the first occurrence of any invalid character
    if invalid_chars := set(INVALID_URL_CHARS).intersection(validated_name):
        raise ValueError(
            f"Invalid {name_type!s} name {validated_name!r}, cannot contain characters: {join_reprs(invalid_chars)}"
        )


def validate_aliases(aliases: Collection[str] | str) -> list[str]:
    """Validate the artifact aliases and return them as a list.

    Raises:
        ValueError: If any of the aliases contain invalid characters.
    """
    aliases_list = always_list(aliases)

    if any(INVALID_ARTIFACT_CHARS.intersection(alias) for alias in aliases_list):
        raise ValueError(
            f"Aliases must not contain any of the following characters: {join_reprs(INVALID_ARTIFACT_CHARS)}"
        )
    return aliases_list


def validate_artifact_types_list(artifact_types: list[str]) -> list[str]:
    """Return True if the artifact types list is valid, False otherwise."""
    artifact_types = always_list(artifact_types)

    if any(
        INVALID_ARTIFACT_CHARS.intersection(typ) or (len(typ) > MAX_NAME_LEN)
        for typ in artifact_types
    ):
        raise ValueError(
            f"Artifact types must not contain any of the following characters: {join_reprs(INVALID_ARTIFACT_CHARS)} "
            f"and must be less than equal to {MAX_NAME_LEN!r} characters"
        )
    return artifact_types


VALID_TAG_PATTERN: re.Pattern[str] = re.compile(r"^[-\w]+( +[-\w]+)*$")


def validate_tags(tags: Collection[str] | str) -> list[str]:
    """Validate the artifact tag names and return them as a deduped list.

    In the case of duplicates, only keep the first tag, and otherwise maintain the order of appearance.

    Raises:
        ValueError: If any of the tags contain invalid characters.
    """
    tags_list = always_list(tags)

    if not all(VALID_TAG_PATTERN.match(tag) for tag in tags_list):
        raise ValueError(
            "Invalid tag(s).  "
            "Tags must only contain alphanumeric characters separated by hyphens, underscores, and/or spaces."
        )
    return list(dict.fromkeys(tags_list))


RESERVED_ARTIFACT_TYPE_PREFIX: Final[str] = "wandb-"
RESERVED_ARTIFACT_NAME_PREFIXES: Final[dict[str, str]] = {
    "job": "",  # "job" artifact type is always reserved for internal use regardless of artifact name
    "run_table": "run-",
    "code": "source-",
}


def validate_artifact_type(typ: str, name: str) -> str:
    """Validate the artifact type and return it as a string."""
    # Check if the artifact *type* matches a reserved prefix
    if typ.startswith(RESERVED_ARTIFACT_TYPE_PREFIX):
        raise ValueError(
            f"Artifact type {typ!r} is reserved for internal use. Please use a different type."
        )

    if (
        # For certain artifact types, check if the artifact *name* matches a reserved prefix
        ((reserved_name_prefix := RESERVED_ARTIFACT_NAME_PREFIXES.get(typ)) is not None)
        and name.startswith(reserved_name_prefix)
    ):
        raise ValueError(
            f"Artifact type {typ!r} is reserved for internal use. Please use a different type."
        )

    return typ


def validate_metadata(metadata: dict[str, Any] | str | None) -> dict[str, Any]:
    """Validate the artifact metadata and return it as a dict."""
    if metadata is None:
        return {}
    if isinstance(metadata, str):
        return from_json(metadata) if metadata else {}
    if isinstance(metadata, dict):
        return cast(Dict[str, Any], from_json(to_json(json_friendly_val(metadata))))
    raise TypeError(f"Invalid artifact metadata type: {type(metadata)!r}")


def validate_ttl_duration_seconds(gql_ttl_duration_seconds: int | None) -> int | None:
    """Validate the `ttlDurationSeconds` value (if any) from a GraphQL response."""
    # If gql_ttl_duration_seconds is not positive, its indicating that TTL is DISABLED(-2)
    # gql_ttl_duration_seconds only returns None if the server is not compatible with setting Artifact TTLs
    if gql_ttl_duration_seconds and gql_ttl_duration_seconds > 0:
        return gql_ttl_duration_seconds
    return None


# ----------------------------------------------------------------------------
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


def remove_registry_prefix(project: str) -> str:
    if is_artifact_registry_project(project):
        return project[len(REGISTRY_PREFIX) :]
    raise ValueError(
        f"Project {project!r} does not have the prefix {REGISTRY_PREFIX}. It is not a registry project"
    )


@pydantic_dataclass
class ArtifactPath:
    #: The collection name.
    name: str
    #: The project name, which can also be a registry name.
    project: Optional[str] = None  # noqa: UP045
    #: Prefix is often an org or entity name.
    prefix: Optional[str] = None  # noqa: UP045

    @classmethod
    def from_str(cls, path: str) -> Self:
        """Instantiate by parsing an artifact path."""
        if len(parts := path.split("/")) <= 3:
            return cls(*reversed(parts))
        raise ValueError(
            f"Expected a valid path like `name`, `project/name`, or `prefix/project/name`.  Got: {path!r}"
        )

    def to_str(self) -> str:
        """Returns the slash-separated string representation of the path."""
        return "/".join(filter(bool, reversed(astuple(self))))

    def with_defaults(
        self,
        prefix: str | None = None,
        project: str | None = None,
    ) -> Self:
        """Returns this path with missing values set to the given defaults."""
        return replace(
            self,
            prefix=self.prefix or prefix,
            project=self.project or project,
        )
