from __future__ import annotations

import logging
from collections.abc import Collection
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, TypeVar, overload

from wandb._strutils import b64decode_ascii, ensureprefix, repr_join
from wandb.proto import wandb_internal_pb2 as pb

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from wandb.apis.public import ArtifactCollection
    from wandb.apis.public.registries.registry import Registry
    from wandb.apis.public.service_api import ServiceApi


T = TypeVar("T")


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
def prepare_registry_filter(query: str, path=...) -> str: ...
@overload
def prepare_registry_filter(query: dict[str, Any], path=...) -> dict[str, Any]: ...
@overload
def prepare_registry_filter(query: list[T] | tuple[T], path=...) -> list[T]: ...
@overload
def prepare_registry_filter(query: T, path=...) -> T: ...


def prepare_registry_filter(query: Any, path: tuple[int | str, ...] = ()) -> Any:
    """Normalize a registry filter as a JSON-serializable GraphQL input.

    Recursively prepend the registry prefix under "name" keys, excluding regex ops.

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

    match query:
        case str() as txt if "name" in path and "$regex" not in path:
            return ensureprefix(txt, REGISTRY_PREFIX)
        case dict() as dct:
            return {k: prepare_registry_filter(v, (*path, k)) for k, v in dct.items()}
        case list() | tuple() as seq:
            return [prepare_registry_filter(v, (*path, i)) for i, v in enumerate(seq)]
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
    if not service_api.feature_enabled(pb.ARTIFACT_COLLECTIONS_FILTERING_SORTING):
        return False

    from wandb.sdk.artifacts._generated import (
        FETCH_ADVANCED_REGISTRY_FEATURES_GQL,
        FetchAdvancedRegistryFeatures,
    )

    try:
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
        org.advanced_registry_features
        and org.advanced_registry_features.advanced_search
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
