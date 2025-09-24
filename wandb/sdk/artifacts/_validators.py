"""Internal validation utilities that are specific to artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Optional, TypeVar, cast

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Concatenate, ParamSpec, Self

from wandb._iterutils import always_list, unique_list
from wandb._pydantic import from_json, gql_typename
from wandb._strutils import nameof, removeprefix
from wandb.util import json_friendly_val

from ._generated import ArtifactPortfolioTypeFields, ArtifactSequenceTypeFields
from .exceptions import ArtifactFinalizedError, ArtifactNotLoggedError

if TYPE_CHECKING:
    from typing import Collection, Final

    from wandb.sdk.artifacts.artifact import Artifact

ArtifactT = TypeVar("ArtifactT", bound="Artifact")
SelfT = TypeVar("SelfT")
R = TypeVar("R")
P = ParamSpec("P")

REGISTRY_PREFIX: Final[str] = "wandb-registry-"
MAX_ARTIFACT_METADATA_KEYS: Final[int] = 100

ARTIFACT_NAME_MAXLEN: Final[int] = 128
ARTIFACT_NAME_INVALID_CHARS: Final[frozenset[str]] = frozenset({"/"})

LINKED_ARTIFACT_COLLECTION_TYPE: Final[str] = gql_typename(ArtifactPortfolioTypeFields)
SOURCE_ARTIFACT_COLLECTION_TYPE: Final[str] = gql_typename(ArtifactSequenceTypeFields)


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

    if not name:
        raise ValueError("Project name cannot be empty")
    if not (registry_name := removeprefix(name, REGISTRY_PREFIX)):
        raise ValueError("Registry name cannot be empty")

    if len(name) > max_len:
        if registry_name != name:
            msg = f"Invalid registry name {registry_name!r}, must be {max_len - len(REGISTRY_PREFIX)} characters or less"
        else:
            msg = f"Invalid project name {name!r}, must be {max_len} characters or less"
        raise ValueError(msg)

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


TAG_REGEX: re.Pattern[str] = re.compile(r"^[-\w]+( +[-\w]+)*$")
"""Regex pattern for valid tag names."""


def validate_tags(tags: Collection[str] | str) -> list[str]:
    """Validate the artifact tag names and return them as a deduped list.

    In the case of duplicates, only keep the first tag, and otherwise maintain the order of appearance.

    Raises:
        ValueError: If any of the tags contain invalid characters.
    """
    tags_list = unique_list(always_list(tags))
    if any(not TAG_REGEX.match(tag) for tag in tags_list):
        raise ValueError(
            "Invalid tag(s).  "
            "Tags must only contain alphanumeric characters separated by hyphens, underscores, and/or spaces."
        )
    return tags_list


RESERVED_ARTIFACT_TYPE_PREFIX: Final[str] = "wandb-"
"""Internal, reserved artifact type prefix."""

RESERVED_ARTIFACT_NAME_PREFIX_BY_TYPE: Final[dict[str, str]] = {
    "job": "",  # Empty prefix means ALL artifact names are reserved for this artifact type
    "run_table": "run-",
    "code": "source-",
}
"""Lookup of internal, reserved `Artifact.name` prefixes by `Artifact.type`."""


def validate_artifact_type(typ: str, name: str) -> str:
    """Validate the artifact type and return it as a string."""
    if (
        # Check if the artifact name is disallowed, based on the artifact type
        (
            # This check MUST be against `None`, since "" disallows ALL artifact names
            (bad_prefix := RESERVED_ARTIFACT_NAME_PREFIX_BY_TYPE.get(typ)) is not None
            and name.startswith(bad_prefix)
        )
        or
        # Check if the artifact type is disallowed
        typ.startswith(RESERVED_ARTIFACT_TYPE_PREFIX)
    ):
        raise ValueError(
            f"Artifact type {typ!r} is reserved for internal use. "
            "Please use a different type."
        )
    return typ


def validate_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the artifact metadata and return it as a dict."""
    if metadata is None:
        return {}
    if isinstance(metadata, str):
        return from_json(metadata) if metadata else {}
    if isinstance(metadata, dict):
        return cast(Dict[str, Any], json.loads(json.dumps(json_friendly_val(metadata))))
    raise TypeError(f"metadata must be dict, not {type(metadata)}")


def validate_ttl_duration_seconds(gql_ttl_duration_seconds: int | None) -> int | None:
    """Validate the `ttlDurationSeconds` value (if any) from a GraphQL response."""
    # If gql_ttl_duration_seconds is not positive, its indicating that TTL is DISABLED(-2)
    # gql_ttl_duration_seconds only returns None if the server is not compatible with setting Artifact TTLs
    if gql_ttl_duration_seconds and gql_ttl_duration_seconds > 0:
        return gql_ttl_duration_seconds
    return None


# ----------------------------------------------------------------------------
MethodT = Callable[Concatenate[SelfT, P], R]
"""Generic type hint for an instance method, e.g. for use with decorators."""


def ensure_logged(method: MethodT[ArtifactT, P, R]) -> MethodT[ArtifactT, P, R]:
    """Decorator to ensure that an Artifact method can only be called if the artifact has been logged.

    If the method is called on an artifact that's not logged, `ArtifactNotLoggedError` is raised.
    """
    # For clarity, use the qualified (full) name of the method
    method_fullname = nameof(method)

    @wraps(method)
    def wrapper(self: ArtifactT, *args: P.args, **kwargs: P.kwargs) -> R:
        if self.is_draft():
            raise ArtifactNotLoggedError(fullname=method_fullname, obj=self)
        return method(self, *args, **kwargs)

    return wrapper


def ensure_not_finalized(method: MethodT[ArtifactT, P, R]) -> MethodT[ArtifactT, P, R]:
    """Decorator to ensure that an `Artifact` method can only be called if the artifact isn't finalized.

    If the method is called on an artifact that's not logged, `ArtifactFinalizedError` is raised.
    """
    # For clarity, use the qualified (full) name of the method
    method_fullname = nameof(method)

    @wraps(method)
    def wrapper(self: ArtifactT, *args: P.args, **kwargs: P.kwargs) -> R:
        if self._final:
            raise ArtifactFinalizedError(fullname=method_fullname, obj=self)
        return method(self, *args, **kwargs)

    return wrapper


def is_artifact_registry_project(project: str) -> bool:
    return project.startswith(REGISTRY_PREFIX)


def remove_registry_prefix(project: str) -> str:
    if not is_artifact_registry_project(project):
        raise ValueError(
            f"Project {project!r} does not have the prefix {REGISTRY_PREFIX}. It is not a registry project"
        )
    return removeprefix(project, REGISTRY_PREFIX)


@pydantic_dataclass
class ArtifactPath:
    name: str
    """The collection or artifact version name."""
    project: Optional[str] = None  # noqa: UP045
    """The project name."""
    prefix: Optional[str] = None  # noqa: UP045
    """Typically the entity or org name."""

    @classmethod
    def from_str(cls, path: str) -> Self:
        """Instantiate by parsing a string artifact path.

        Raises:
            ValueError: If the string is not a valid artifact path.
        """
        # Separate the alias first, which may itself contain slashes.
        # If there's no alias, note that both sep and alias will be empty.
        collection_path, sep, alias = path.partition(":")

        prefix, project = None, None  # defaults, if missing
        if len(parts := collection_path.split("/")) == 1:
            name = parts[0]
        elif len(parts) == 2:
            project, name = parts
        elif len(parts) == 3:
            prefix, project, name = parts
        else:
            raise ValueError(f"Invalid artifact path: {path!r}")
        return cls(prefix=prefix, project=project, name=f"{name}{sep}{alias}")

    def to_str(self) -> str:
        """Returns the slash-separated string representation of the path."""
        ordered_parts = (self.prefix, self.project, self.name)
        return "/".join(part for part in ordered_parts if part)

    def with_defaults(
        self,
        *,
        prefix: str | None = None,
        project: str | None = None,
    ) -> Self:
        """Returns a copy of this path with missing values set to the given defaults."""
        return replace(
            self,
            prefix=self.prefix or prefix,
            project=self.project or project,
        )

    def is_registry_path(self) -> bool:
        """Returns True if this path appears to be a registry path."""
        return bool((p := self.project) and is_artifact_registry_project(p))


@pydantic_dataclass
class FullArtifactPath(ArtifactPath):
    """Same as ArtifactPath, but with all parts required."""

    name: str
    project: str
    prefix: str
