from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from operator import attrgetter
from typing import TYPE_CHECKING, Annotated, Any, Final, TypeVar, overload

from pydantic import BeforeValidator, ValidationInfo
from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Self

from wandb._filters import transform_fields
from wandb._filters.operators import KEY_TO_OP
from wandb._iterutils import always_list
from wandb._strutils import b64decode_ascii, ensureprefix, repr_join
from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:
    from wandb.apis.public import ArtifactCollection
    from wandb.apis.public.registries.registry import Registry
    from wandb.apis.public.service_api import ServiceApi

logger = logging.getLogger(__name__)


T = TypeVar("T")

ADVANCED_SEARCH_CTX_KEY: Final[str] = "advanced_search_enabled"
"""Pydantic validation context key signaling that advanced search is enabled."""


@pydantic_dataclass(frozen=True, slots=True)
class SearchField:
    """Canonical and accepted filter field names for basic and advanced search.

    Each tuple contains the canonical name first, followed by accepted aliases.
    ``None`` means the field is unsupported in that mode.
    """

    basic: Annotated[tuple[str, ...], BeforeValidator(always_list)] | None = None
    advanced: Annotated[tuple[str, ...], BeforeValidator(always_list)] | None = None

    def __post_init__(self) -> None:
        if not (self.basic or self.advanced):
            raise ValueError("A filter field must support at least one search mode.")

    @classmethod
    def basic_only(cls, canonical: str, *aliases: str) -> Self:
        """Defines a field supported in basic search only."""
        return cls(basic=(canonical, *aliases), advanced=None)

    @classmethod
    def advanced_only(cls, canonical: str, *aliases: str) -> Self:
        """Defines a field supported in advanced search only."""
        return cls(basic=None, advanced=(canonical, *aliases))

    @classmethod
    def shared(cls, canonical: str, *aliases: str) -> Self:
        """Defines a field supported in both search modes with the same canonical name."""
        return cls(basic=(canonical, *aliases), advanced=(canonical, *aliases))


@dataclass(frozen=True, slots=True)
class VersionsFilterFields:
    """Filter-field aliases for each Versions filter argument."""

    registry_fields: tuple[SearchField, ...]
    collection_fields: tuple[SearchField, ...]
    artifact_fields: tuple[SearchField, ...]

    def resolve_aliases(self, info: ValidationInfo) -> dict[str, str]:
        """Resolve aliases for the model field and search mode being validated."""
        context = info.context if isinstance(info.context, dict) else {}
        return self.aliases_for(
            info.field_name,
            advanced=bool(context.get(ADVANCED_SEARCH_CTX_KEY)),
        )

    def aliases_for(self, name: str, *, advanced: bool = False) -> dict[str, str]:
        """Map accepted aliases to canonical names for one filter and mode."""
        match name:
            case "registry_filter":
                fields = self.registry_fields
            case "collection_filter":
                fields = self.collection_fields
            case "artifact_filter":
                fields = self.artifact_fields
            case _:
                raise ValueError(f"Unknown Versions filter argument: {name!r}.")

        aliases_per_field = map(attrgetter("advanced" if advanced else "basic"), fields)
        return {
            alias: aliases[0]
            for aliases in aliases_per_field
            if aliases
            for alias in aliases
        }


VERSIONS_FILTER_FIELDS = VersionsFilterFields(
    registry_fields=(
        SearchField.shared("name"),
        SearchField(
            basic=("id",),
            advanced=("project_id", "id"),
        ),
        SearchField.shared("entity_id"),
        SearchField.basic_only("description"),
        SearchField.basic_only("created_at"),
        SearchField.basic_only("updated_at"),
    ),
    collection_fields=(
        SearchField.shared("name", "collection_name", "artifact_collection_name"),
        SearchField(
            basic=("id", "collection_id", "artifact_collection_id"),
            advanced=("artifact_collection_id", "id", "collection_id"),
        ),
        SearchField.shared("tag", "tags"),
        SearchField.basic_only("description"),
        SearchField.basic_only("created_at"),
        SearchField.basic_only("updated_at"),
    ),
    artifact_fields=(
        SearchField(
            basic=("id",),
            advanced=("artifact_id", "id"),
        ),
        SearchField.shared("version", "version_index"),
        SearchField.shared("tag", "tags"),
        SearchField.shared("alias", "aliases"),
        SearchField.shared("metadata", "artifact_metadata"),
        SearchField(
            basic=("created_at",),
            advanced=("artifact_created_at", "created_at"),
        ),
        SearchField.basic_only("updated_at"),
        SearchField.advanced_only("acm_created_at"),
        SearchField.advanced_only("acm_updated_at"),
        SearchField.advanced_only("artifact_size"),
        SearchField.advanced_only("artifact_file_count"),
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
