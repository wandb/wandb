from __future__ import annotations

from collections.abc import Collection
from enum import Enum
from functools import lru_cache, partial
from typing import TYPE_CHECKING, Any, TypeVar, overload

from wandb._strutils import ensureprefix

if TYPE_CHECKING:
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
            expected = ",".join(repr(e.value) for e in cls)
            raise ValueError(
                f"Invalid visibility {value!r} from backend. Expected one of: {expected}"
            ) from None

    @classmethod
    def from_python(cls, name: str) -> Visibility:
        """Convert a visibility string to a `Visibility` enum."""
        try:
            return cls(name)
        except ValueError:
            expected = ",".join(repr(e.name) for e in cls)
            raise ValueError(
                f"Invalid visibility {name!r}. Expected one of: {expected}"
            ) from None


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
def ensure_registry_prefix_on_names(query: str, in_name: bool = ...) -> str: ...
@overload
def ensure_registry_prefix_on_names(
    query: dict[str, Any], in_name: bool = ...
) -> dict[str, Any]: ...
@overload
def ensure_registry_prefix_on_names(
    query: list[T] | tuple[T], in_name: bool = ...
) -> list[T]: ...
@overload
def ensure_registry_prefix_on_names(query: T, in_name: bool = ...) -> T: ...


def ensure_registry_prefix_on_names(query: Any, in_name: bool = False) -> Any:
    """Recursively prepend the registry prefix under "name" keys, excluding regex ops.

    - in_name: True if we are under a "name" key (or propagating from one).

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

    match query:
        case str() as txt:
            return ensureprefix(txt, REGISTRY_PREFIX) if in_name else txt
        case dict() as dct:
            new_dict = {}
            for k, v in dct.items():
                if k == "$regex":
                    # For regex operator, we skip transformation of its value.
                    new_dict[k] = v
                else:
                    # Enforce prefix on "name" keys, otherwise propagate flags as-is.
                    new_dict[k] = ensure_registry_prefix_on_names(
                        v, in_name=(k == "name") or in_name
                    )
            return new_dict
        case list() | tuple() as seq:
            return list(
                map(partial(ensure_registry_prefix_on_names, in_name=in_name), seq)
            )
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
