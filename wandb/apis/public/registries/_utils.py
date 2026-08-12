from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, TypeVar, overload

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Self

from wandb._filters import transform_fields
from wandb._filters.operators import KEY_TO_OP
from wandb._strutils import b64decode_ascii, ensureprefix, repr_join
from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:
    from wandb.apis.public import ArtifactCollection
    from wandb.apis.public.registries.registry import Registry
    from wandb.apis.public.service_api import ServiceApi

logger = logging.getLogger(__name__)


T = TypeVar("T")


@pydantic_dataclass(frozen=True, slots=True)
class _FieldNames:
    canonical: str  #: The canonical name of the field.
    aliases: tuple[str, ...] = ()  #: Accepted aliases for the field.


@pydantic_dataclass(frozen=True, slots=True)
class SearchField:
    """Canonical and accepted filter field names for basic and advanced search.

    In each sequence, the CANONICAL name comes first. Remaining names, if any,
    are acceptable aliases.

    A `None` value means the field is unsupported in that search mode.
    """

    basic: _FieldNames | None
    advanced: _FieldNames | None

    def __post_init__(self) -> None:
        if not (self.basic or self.advanced):
            raise ValueError("A filter field must support at least one search mode.")

    @classmethod
    def from_shared(cls, name: str, *aliases: str) -> Self:
        """Defines a filter field for either search mode with the same allowed aliases."""
        return cls(
            basic=_FieldNames(name, aliases=aliases),
            advanced=_FieldNames(name, aliases=aliases),
        )


@dataclass(frozen=True, slots=True)
class SearchFields:
    """Filter-field aliases for one registry search surface."""

    fields: tuple[SearchField, ...]

    def advanced_aliases(self) -> dict[str, str]:
        # Be sure to include the canonical name in the map
        return {
            alias: names.canonical
            for field in self.fields
            if (names := field.advanced)
            for alias in (names.canonical, *names.aliases)
        }

    def basic_aliases(self) -> dict[str, str]:
        # Be sure to include the canonical name in the map
        return {
            alias: names.canonical
            for field in self.fields
            if (names := field.basic)
            for alias in (names.canonical, *names.aliases)
        }


REGISTRIES_FILTER_FIELDS = SearchFields(
    fields=(
        SearchField(
            basic=_FieldNames("id"),
            advanced=_FieldNames("project_id", aliases=["id"]),
        ),
        SearchField.from_shared("name"),
        SearchField.from_shared("entity_id"),
        # Only supported in "basic" search
        SearchField(
            basic=_FieldNames("description"),
            advanced=None,
        ),
        SearchField(
            basic=_FieldNames("created_at"),
            advanced=None,
        ),
        SearchField(
            basic=_FieldNames("updated_at"),
            advanced=None,
        ),
    )
)
"""Defines allowed field names in registry filters.

Note: "advanced" fields are only relevant when passing a filter to a Versions paginator.
"""

COLLECTIONS_FILTER_FIELDS = SearchFields(
    fields=(
        SearchField.from_shared("artifact_collection_id", "collection_id", "id"),
        SearchField(
            basic=_FieldNames("name"),
            advanced=_FieldNames(
                "name", aliases=("collection_name", "artifact_collection_name")
            ),
        ),
        SearchField(
            basic=_FieldNames("tag"),
            advanced=_FieldNames("tag", aliases=("tags",)),
        ),
        # Only supported in "basic" search
        SearchField(
            basic=_FieldNames("description"),
            advanced=None,
        ),
        SearchField(
            basic=_FieldNames("created_at"),
            advanced=None,
        ),
        SearchField(
            basic=_FieldNames("updated_at"),
            advanced=None,
        ),
    )
)
"""Defines allowed field names in artifact collection filters.

Note: "advanced" fields are only relevant when passing a filter to a Versions paginator.
"""

VERSIONS_FILTER_FIELDS = SearchFields(
    fields=(
        SearchField(
            basic=_FieldNames("id"),
            advanced=_FieldNames("artifact_id", aliases=["id"]),
        ),
        SearchField(
            basic=_FieldNames("version"),
            advanced=_FieldNames("version", aliases=("version_index",)),
        ),
        SearchField(
            basic=_FieldNames("tag"),
            advanced=_FieldNames("tag", aliases=("tags",)),
        ),
        SearchField(
            basic=_FieldNames("alias"),
            advanced=_FieldNames("alias", aliases=("aliases",)),
        ),
        SearchField(
            basic=_FieldNames("metadata"),
            advanced=_FieldNames("metadata", aliases=("artifact_metadata",)),
        ),
        SearchField(
            basic=_FieldNames("created_at"),
            advanced=_FieldNames("artifact_created_at", aliases=["created_at"]),
        ),
        # Only supported in "basic" search
        SearchField(
            basic=_FieldNames("updated_at"),
            advanced=None,
        ),
        # Only supported in "advanced" search
        SearchField(
            basic=None,
            advanced=_FieldNames("artifact_size"),
        ),
    )
)
"""Defines allowed field names in artifact version filters.

Note: "advanced" fields are only relevant when passing the filter to a Versions paginator.
"""


class Visibility(str, Enum):
    # names are what users see/pass into Python methods
    # values are what's expected by backend API
    organization = "PRIVATE"
    restricted = "RESTRICTED"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        # Allow instantiation from enum names too (e.g. "organization" or "restricted")
        return cls.__members__.get(value)

    @classmethod
    def from_gql(cls, value: str) -> Visibility:
        """Convert a GraphQL `visibility` value to a Visibility enum."""
        try:
            return cls(value)
        except ValueError:
            msg = f"Invalid visibility {value!r} from backend. Expected one of: {repr_join(e.value for e in cls)}"
            raise ValueError(msg) from None

    @classmethod
    def from_project_access(cls, value: str | None) -> Visibility:
        """Convert a GraphQL project ``access`` value to a Visibility enum.

        Registry search may return legacy or non-registry access levels (e.g.
        ``USER_READ``) for organization projects. Treat those as organization
        visibility so registry listing can proceed.
        """
        if not value:
            return cls.organization
        try:
            return cls(value)
        except ValueError:
            if value == "RESTRICTED":
                return cls.restricted
            return cls.organization

    @classmethod
    def from_python(cls, name: str) -> Visibility:
        """Convert a visibility string to a `Visibility` enum."""
        try:
            return cls(name)
        except ValueError:
            msg = f"Invalid visibility {name!r}. Expected one of: {repr_join(e.name for e in cls)}"
            raise ValueError(msg) from None


def prepare_artifact_types_input(
    artifact_types: Collection[str] | None,
) -> list[dict[str, str]] | None:
    """Format the artifact types for the GQL input.

    Args:
        artifact_types: The artifact types to add to the registry.

    Returns:
        The artifact types for the GQL input.
    """
    from wandb.sdk.artifacts._validators import validate_artifact_types

    if artifact_types:
        return [{"name": typ} for typ in validate_artifact_types(artifact_types)]
    return None


def prefix_registry_name(operand: Any) -> Any:
    """Prefix strings in a registry-name operand, except regexes and unknown ops."""
    from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

    match operand:
        case str(txt):
            return ensureprefix(txt, REGISTRY_PREFIX)
        case dict(dct):
            return {
                k: (
                    v
                    if isinstance(k, str)
                    and (k == "$regex" or (k.startswith("$") and k not in KEY_TO_OP))
                    else prefix_registry_name(v)
                )
                for k, v in dct.items()
            }
        case list(seq) | tuple(seq):
            return [prefix_registry_name(value) for value in seq]
        case _:
            return operand


@overload
def prepare_registry_filter(query: str) -> str: ...
@overload
def prepare_registry_filter(query: dict[str, Any]) -> dict[str, Any]: ...
@overload
def prepare_registry_filter(query: list[T] | tuple[T, ...]) -> list[T]: ...
@overload
def prepare_registry_filter(query: T) -> T: ...


def prepare_registry_filter(query: Any) -> Any:
    """Normalize a registry filter as a JSON-serializable GraphQL input.

    Prepend the registry prefix to ``name`` operands, excluding regex operands
    and opaque unknown-operator subtrees.

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    match query:
        case dict():
            return transform_fields(
                query,
                operand_transforms={"name": prefix_registry_name},
            )
        case list() | tuple():
            return [prepare_registry_filter(value) for value in query]
        case _:
            return query


@lru_cache(maxsize=10)
def fetch_org_entity_from_organization(
    service_api: ServiceApi, organization: str
) -> str:
    """Fetch the org entity from the organization.

    Args:
        service_api: The service API instance to use for querying W&B.
        organization (str): The organization to fetch the org entity for.
    """
    from wandb.sdk.artifacts._generated import FETCH_ORGANIZATION_GQL, FetchOrganization

    gql_op = FETCH_ORGANIZATION_GQL
    gql_vars = {"org": organization}
    try:
        data = service_api.execute_graphql(gql_op, variables=gql_vars)
    except Exception as e:
        msg = f"Error fetching org entity for organization: {organization!r}"
        raise ValueError(msg) from e

    result = FetchOrganization.model_validate(data)
    if (
        not (org := result.organization)
        or not (org_entity := org.org_entity)
        or not (org_name := org_entity.name)
    ):
        raise ValueError(f"Organization entity for {organization!r} not found.")

    return org_name


def _project_id_from_gql_id(gql_id: str) -> int | None:
    try:
        decoded = b64decode_ascii(gql_id)
    except (ValueError, UnicodeDecodeError):
        logger.warning("Invalid project ID: %r", gql_id)
        return None

    match decoded.split(":"):
        case ["Project", idx] if idx.isdigit():
            return int(idx)
        case ["ProjectInternalId", idx] if idx.isdigit():
            return int(idx)
        case _:
            logger.warning("Invalid project ID: %r", gql_id)
            return None


def filter_for_registry(registry: Registry) -> dict[str, Any]:
    if (project_encoded_id := registry.internal_id) and (
        project_id := _project_id_from_gql_id(project_encoded_id)
    ):
        return {"id": project_id}
    return {"name": registry.full_name}


@lru_cache(maxsize=10)
def advanced_search_enabled(service_api: ServiceApi, organization: str) -> bool:
    """Whether the organization has ClickHouse-backed advanced registry search.

    The ``advancedRegistryFeatures`` GQL field was added in server 0.78.x alongside
    ``ARTIFACT_COLLECTIONS_FILTERING_SORTING``. We use that feature flag as a proxy
    to avoid querying an endpoint that does not exist on older servers.
    """
    try:
        if not service_api.feature_enabled(pb.ARTIFACT_COLLECTIONS_FILTERING_SORTING):
            return False

        from wandb.sdk.artifacts._generated import (
            FETCH_ADVANCED_REGISTRY_FEATURES_GQL,
            FetchAdvancedRegistryFeatures,
        )

        result = service_api.execute_graphql(
            FETCH_ADVANCED_REGISTRY_FEATURES_GQL,
            variables={"organization": organization},
            parse=FetchAdvancedRegistryFeatures.model_validate_json,
        )
    except Exception:
        logger.warning(
            "Failed to fetch advanced registry features for organization: %r",
            organization,
        )
        return False

    if not (org := result.organization):
        logger.warning("Organization %r not found.", organization)
        return False
    return bool(
        (features := org.advanced_registry_features) and features.advanced_search
    )


def registry_filter_for_collection(collection: ArtifactCollection) -> dict[str, Any]:
    if (project_encoded_id := collection.project_internal_id) and (
        project_id := _project_id_from_gql_id(project_encoded_id)
    ):
        return {"id": project_id}
    return {"name": collection.project}
