from __future__ import annotations

from enum import Enum
from functools import lru_cache, partial
from typing import TYPE_CHECKING, Any, Collection

from wandb_gql import gql

from wandb._strutils import ensureprefix

if TYPE_CHECKING:
    from wandb.apis.public.api import RetryingClient


class Visibility(str, Enum):
    # names are what users see/pass into Python methods
    # values are what's expected by backend API
    organization = "PRIVATE"
    restricted = "RESTRICTED"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
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


def ensure_registry_prefix_on_names(obj: Any, /, in_name: bool = False) -> Any:
    """Recursively the registry prefix to values under "name" keys, excluding regex ops.

    - in_name: True if we are under a "name" key (or propagating from one).

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

    if isinstance(obj, str):
        return ensureprefix(obj, REGISTRY_PREFIX) if in_name else obj
    if isinstance(obj, dict):
        return {
            k: (
                # For regex operator, we skip transformation of its value.
                v
                if k == "$regex"
                # For "name", set `in_name=True` to ensure the prefix is applied.
                # For any other key, propagate flags as-is.
                else ensure_registry_prefix_on_names(
                    v, in_name=(k == "name" or in_name)
                )
            )
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return list(map(partial(ensure_registry_prefix_on_names, in_name=in_name), obj))
    return obj


@lru_cache(maxsize=10)
def fetch_org_entity_from_organization(
    client: RetryingClient, organization: str
) -> str:
    """Fetch the org entity from the organization.

    Args:
        client (Client): Graphql client.
        organization (str): The organization to fetch the org entity for.
    """
    from wandb.sdk.artifacts._generated import (
        FETCH_ORG_ENTITY_FROM_ORGANIZATION_GQL,
        FetchOrgEntityFromOrganization,
    )

    gql_op = gql(FETCH_ORG_ENTITY_FROM_ORGANIZATION_GQL)
    try:
        data = client.execute(gql_op, variable_values={"organization": organization})
    except Exception as e:
        msg = f"Error fetching org entity for organization: {organization!r}"
        raise ValueError(msg) from e

    result = FetchOrgEntityFromOrganization.model_validate(data)
    if (
        not (org := result.organization)
        or not (org_entity := org.org_entity)
        or not (org_name := org_entity.name)
    ):
        raise ValueError(f"Organization entity for {organization!r} not found.")

    return org_name
