from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Final, TypeVar, overload

from pydantic import ValidationInfo
from pydantic.dataclasses import dataclass as pydantic_dataclass

from wandb._filters import FilterFieldTransformer
from wandb._filters.operators import KEY_TO_OP
from wandb._strutils import b64decode_ascii, ensureprefix, repr_join
from wandb.proto import wandb_internal_pb2 as pb

_logger = logging.getLogger(__name__)

ADVANCED_SEARCH_CTX_KEY: Final[str] = "advanced_search_enabled"

if TYPE_CHECKING:
    from wandb.apis.public import ArtifactCollection
    from wandb.apis.public.registries.registry import Registry
    from wandb.apis.public.service_api import ServiceApi


T = TypeVar("T")


@pydantic_dataclass(frozen=True, slots=True)
class FilterFieldAlias:
    """Canonical and accepted filter field names for basic and advanced search.

    Each tuple contains the canonical name first, followed by accepted aliases.
    ``None`` means the field is unsupported in that mode.
    """

    basic: tuple[str, ...] | None = None
    advanced: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not (self.basic or self.advanced):
            raise ValueError("A filter field must support at least one search mode.")


@dataclass(frozen=True, slots=True)
class VersionsFilterFields:
    """Field-name policies for each Versions filter argument."""

    registry_filter: tuple[FilterFieldAlias, ...]
    collection_filter: tuple[FilterFieldAlias, ...]
    artifact_filter: tuple[FilterFieldAlias, ...]

    def resolve(self, info: ValidationInfo) -> dict[str, str]:
        """Resolve aliases for the model field and search mode being validated."""
        if (name := info.field_name) is None:
            raise ValueError("A Versions filter policy requires a model field name.")

        context = info.context if isinstance(info.context, dict) else {}
        return self.for_filter(
            name,
            advanced=bool(context.get(ADVANCED_SEARCH_CTX_KEY)),
        )

    def for_filter(self, name: str, *, advanced: bool) -> dict[str, str]:
        """Return the field-name policy for a Versions filter argument."""
        match name:
            case "registry_filter":
                fields = self.registry_filter
            case "collection_filter":
                fields = self.collection_filter
            case "artifact_filter":
                fields = self.artifact_filter
            case _:
                raise ValueError(f"Unknown Versions filter argument: {name!r}.")

        aliases_by_field = (
            field.advanced if advanced else field.basic for field in fields
        )
        return {
            alias: aliases[0]
            for aliases in aliases_by_field
            if aliases
            for alias in aliases
        }


VERSIONS_FILTER_FIELDS = VersionsFilterFields(
    registry_filter=(
        FilterFieldAlias(basic=("name",), advanced=("name",)),
        FilterFieldAlias(basic=("id",), advanced=("project_id", "id")),
        FilterFieldAlias(basic=("entity_id",), advanced=("entity_id",)),
        FilterFieldAlias(basic=("description",)),
        FilterFieldAlias(basic=("created_at",)),
        FilterFieldAlias(basic=("updated_at",)),
    ),
    collection_filter=(
        FilterFieldAlias(
            basic=("name", "collection_name", "artifact_collection_name"),
            advanced=("name", "collection_name", "artifact_collection_name"),
        ),
        FilterFieldAlias(
            basic=("id", "collection_id", "artifact_collection_id"),
            advanced=("artifact_collection_id", "id", "collection_id"),
        ),
        FilterFieldAlias(basic=("tag", "tags"), advanced=("tag", "tags")),
        FilterFieldAlias(basic=("description",)),
        FilterFieldAlias(basic=("created_at",)),
        FilterFieldAlias(basic=("updated_at",)),
    ),
    artifact_filter=(
        FilterFieldAlias(basic=("id",), advanced=("artifact_id", "id")),
        FilterFieldAlias(
            basic=("version", "version_index"),
            advanced=("version", "version_index"),
        ),
        FilterFieldAlias(basic=("tag", "tags"), advanced=("tag", "tags")),
        FilterFieldAlias(basic=("alias", "aliases"), advanced=("alias", "aliases")),
        FilterFieldAlias(
            basic=("metadata", "artifact_metadata"),
            advanced=("metadata", "artifact_metadata"),
        ),
        FilterFieldAlias(
            basic=("created_at",),
            advanced=("artifact_created_at", "created_at"),
        ),
        FilterFieldAlias(basic=("updated_at",)),
        FilterFieldAlias(advanced=("acm_created_at",)),
        FilterFieldAlias(advanced=("acm_updated_at",)),
        FilterFieldAlias(advanced=("artifact_size",)),
        FilterFieldAlias(advanced=("artifact_file_count",)),
    ),
)


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


@overload
def prepare_registry_filter(query: str) -> str: ...
@overload
def prepare_registry_filter(query: dict[str, Any]) -> dict[str, Any]: ...
@overload
def prepare_registry_filter(query: list[T] | tuple[T, ...]) -> list[T]: ...
@overload
def prepare_registry_filter(query: T) -> T: ...


def prefix_registry_name(operand: Any) -> Any:
    """Prefix strings in a registry-name operand, except regexes and unknown ops."""
    from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

    match operand:
        case str() as txt:
            return ensureprefix(txt, REGISTRY_PREFIX)
        case dict() as dct:
            return {
                key: (
                    value
                    if key == "$regex" or (key.startswith("$") and key not in KEY_TO_OP)
                    else prefix_registry_name(value)
                )
                for key, value in dct.items()
            }
        case list() | tuple() as seq:
            return [prefix_registry_name(value) for value in seq]
        case _:
            return operand


def prepare_registry_filter(query: Any) -> Any:
    """Normalize a registry filter as a JSON-serializable GraphQL input.

    Prepend the registry prefix to ``name`` operands, excluding regex operands
    and opaque unknown-operator subtrees.

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    match query:
        case dict():
            return FilterFieldTransformer(
                lambda field, operand: (
                    field,
                    prefix_registry_name(operand) if field == "name" else operand,
                )
            ).transform(query)
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
        _logger.warning("Invalid project ID: %r", gql_id)
        return None

    match decoded.split(":"):
        case ["Project", idx] if idx.isdigit():
            return int(idx)
        case ["ProjectInternalId", idx] if idx.isdigit():
            return int(idx)
        case _:
            _logger.warning("Invalid project ID: %r", gql_id)
            return None


def filter_for_registry(
    registry: Registry,
    *,
    service_api: ServiceApi,
    organization: str,
) -> dict[str, Any]:
    if (project_encoded_id := registry.internal_id) and (
        project_id := _project_id_from_gql_id(project_encoded_id)
    ):
        return {registry_id_filter_key(service_api, organization): project_id}
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
        _logger.warning(
            "Failed to fetch advanced registry features for organization: %r",
            organization,
        )
        return False

    if not (org := result.organization):
        _logger.warning("Organization %r not found.", organization)
        return False
    return bool(
        (features := org.advanced_registry_features) and features.advanced_search
    )


def registry_id_filter_key(service_api: ServiceApi, organization: str) -> str:
    """Return the registry project filter key for the organization's search backend."""
    if advanced_search_enabled(service_api, organization):
        return "project_id"
    return "id"


def registry_filter_for_collection(
    collection: ArtifactCollection,
    *,
    service_api: ServiceApi,
    organization: str,
) -> dict[str, Any]:
    if (project_encoded_id := collection.project_internal_id) and (
        project_id := _project_id_from_gql_id(project_encoded_id)
    ):
        return {registry_id_filter_key(service_api, organization): project_id}
    return {"name": collection.project}
