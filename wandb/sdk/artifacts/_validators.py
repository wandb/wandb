"""Internal validation utilities that are specific to artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from functools import singledispatch, wraps
from typing import TYPE_CHECKING, Any, Callable, Literal, TypeVar

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Concatenate, ParamSpec, Self

from wandb._iterutils import always_list, unique_list
from wandb._pydantic import from_json
from wandb._strutils import nameof
from wandb.util import json_friendly_val

from .exceptions import ArtifactFinalizedError, ArtifactNotLoggedError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Final

    from wandb.sdk.artifacts.artifact import Artifact

ArtifactT = TypeVar("ArtifactT", bound="Artifact")
SelfT = TypeVar("SelfT")
R = TypeVar("R")
P = ParamSpec("P")

REGISTRY_PREFIX: Final[str] = "wandb-registry-"
MAX_ARTIFACT_METADATA_KEYS: Final[int] = 100

NAME_MAXLEN: Final[int] = 128

INVALID_ARTIFACT_NAME_CHARS: Final[frozenset[str]] = frozenset("/")
INVALID_URL_CHARS: Final[frozenset[str]] = frozenset("/\\#?%:\r\n")
ARTIFACT_SEP_CHARS: Final[frozenset[str]] = frozenset("/:")


@dataclass
class LinkArtifactFields:
    """Keep this list updated with fields where linked and source artifacts differ."""

    entity_name: str
    project_name: str
    name: str
    version: str
    aliases: list[str]

    # These fields shouldn't be user-editable, linked artifacts always have these values
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
    if len(name) > NAME_MAXLEN:
        trunc_name = f"{name[:NAME_MAXLEN]} ..."
        raise ValueError(
            f"Artifact name is longer than {NAME_MAXLEN!r} characters: {trunc_name!r}"
        )

    if INVALID_ARTIFACT_NAME_CHARS.intersection(name):
        raise ValueError(
            "Artifact names must not contain any of the following characters: "
            f"{', '.join(sorted(INVALID_ARTIFACT_NAME_CHARS))}.  Got: {name!r}"
        )

    return name


def validate_project_name(name: str) -> str:
    """Validate a project name according to W&B rules.

    Return the original name if successful.

    Args:
        name: The project name string.

    Raises:
        ValueError: If the name is invalid (too long or contains invalid characters).
    """
    if not name:
        raise ValueError("Project name cannot be empty")
    if not (registry_name := name.removeprefix(REGISTRY_PREFIX)):
        raise ValueError("Registry name cannot be empty")

    if len(name) > NAME_MAXLEN:
        if registry_name != name:
            msg = f"Invalid registry name {registry_name!r}, must be {NAME_MAXLEN - len(REGISTRY_PREFIX)!r} characters or less"
        else:
            msg = f"Invalid project name {name!r}, must be {NAME_MAXLEN!r} characters or less"
        raise ValueError(msg)

    # Find the first occurrence of any invalid character
    if invalid_chars := set(INVALID_URL_CHARS).intersection(name):
        error_name = registry_name or name
        invalid_chars_repr = ", ".join(sorted(map(repr, invalid_chars)))
        raise ValueError(
            f"Invalid project/registry name {error_name!r}, cannot contain characters: {invalid_chars_repr!s}"
        )
    return name


def validate_aliases(aliases: Iterable[str] | str) -> list[str]:
    """Validate the artifact aliases and return them as a list.

    Raises:
        ValueError: If any of the aliases contain invalid characters.
    """
    aliases_list = always_list(aliases)
    if any(ARTIFACT_SEP_CHARS.intersection(name) for name in aliases_list):
        invalid_chars = ", ".join(sorted(map(repr, ARTIFACT_SEP_CHARS)))
        raise ValueError(
            f"Aliases must not contain any of the following characters: {invalid_chars}"
        )
    return aliases_list


def validate_artifact_types(types: Iterable[str] | str) -> list[str]:
    """Validate the artifact type names and return them as a list."""
    types_list = always_list(types)
    if any(ARTIFACT_SEP_CHARS.intersection(name) for name in types_list):
        invalid_chars = ", ".join(sorted(map(repr, ARTIFACT_SEP_CHARS)))
        raise ValueError(
            f"Artifact types must not contain any of the following characters: {invalid_chars}"
        )
    if any(len(name) > NAME_MAXLEN for name in types_list):
        raise ValueError(
            f"Artifact types must be less than or equal to {NAME_MAXLEN!r} characters"
        )
    return types_list


TAG_REGEX: re.Pattern[str] = re.compile(r"^[-\w]+( +[-\w]+)*$")
"""Regex pattern for valid tag names."""


def validate_tags(tags: Iterable[str] | str) -> list[str]:
    """Validate artifact tag names and return them as a deduped list.

    In the case of duplicates, keep the first tag and maintain the order of
    appearance.

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


@singledispatch
def validate_metadata(metadata: dict[str, Any] | str | None) -> dict[str, Any]:
    """Validate the artifact metadata and return it as a dict."""
    raise TypeError(f"Cannot parse {type(metadata)} as artifact metadata")


@validate_metadata.register(type(None))
@validate_metadata.register(str)
def _(metadata: str | None) -> dict[str, Any]:
    return validate_metadata(from_json(metadata)) if metadata else {}


@validate_metadata.register(dict)
def _(metadata: dict[str, Any]) -> dict[str, Any]:
    # NOTE: The backend doesn't currently allow JS-compatible `+/-Infinity` values.
    # Forbid them here to avoid surprises, but revisit if we add future backend support.
    # Note that prior behavior already converts `NaN` values to `None` (client-side).
    metadata = from_json(json.dumps(json_friendly_val(metadata), allow_nan=False))
    if len(metadata) > MAX_ARTIFACT_METADATA_KEYS:
        raise ValueError(
            f"Artifact must not have more than {MAX_ARTIFACT_METADATA_KEYS!r} metadata keys."
        )
    return metadata


def validate_ttl_duration_seconds(ttl_duration_seconds: int) -> int | None:
    """Validate the `ttlDurationSeconds` value from a GraphQL response.

    A non-positive value indicates that TTL is DISABLED (-2), which we
    convert to `None`.
    """
    return ttl_duration_seconds if ttl_duration_seconds > 0 else None


# ----------------------------------------------------------------------------
MethodT = Callable[Concatenate[SelfT, P], R]
"""Generic type hint for an instance method, e.g. for use with decorators."""


def ensure_logged(method: MethodT[ArtifactT, P, R]) -> MethodT[ArtifactT, P, R]:
    """Ensure an artifact method runs only if the artifact has been logged.

    If the method is called on an artifact that's not logged, `ArtifactNotLoggedError`
    is raised.
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
    """Ensure an `Artifact` method runs only if the artifact is not finalized.

    If the method is called on an artifact that's not logged, `ArtifactFinalizedError`
    is raised.
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
            f"Project {project!r} is not a registry project. Must start with: {REGISTRY_PREFIX!r}"
        )
    return project.removeprefix(REGISTRY_PREFIX)


@pydantic_dataclass
class ArtifactPath:
    name: str
    """The collection or artifact version name."""
    project: str | None = None
    """The project name."""
    prefix: str | None = None
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
