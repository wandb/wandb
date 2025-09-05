from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

from wandb._strutils import ensureprefix
from wandb.sdk.artifacts._validators import (
    REGISTRY_PREFIX,
    validate_artifact_types_list,
)

if TYPE_CHECKING:
    from wandb_gql import Client

from wandb_gql import gql


class Visibility(str, Enum):
    # names are what users see/pass into Python methods
    # values are what's expected by backend API
    organization = "PRIVATE"
    restricted = "RESTRICTED"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        return next((e for e in cls if e.name == value), None)


def format_gql_artifact_types_input(
    artifact_types: list[str] | None,
) -> list[dict[str, str]]:
    """Format the artifact types for the GQL input.

    Args:
        artifact_types: The artifact types to add to the registry.

    Returns:
        The artifact types for the GQL input.
    """
    if artifact_types is None:
        return []
    return [{"name": typ} for typ in validate_artifact_types_list(artifact_types)]


def gql_to_registry_visibility(
    visibility: str,
) -> Literal["organization", "restricted"]:
    """Convert the GQL visibility to the registry visibility.

    Args:
        visibility: The GQL visibility.

    Returns:
        The registry visibility.
    """
    try:
        return Visibility(visibility).name
    except ValueError:
        raise ValueError(f"Invalid visibility: {visibility!r} from backend")


def registry_visibility_to_gql(
    visibility: Literal["organization", "restricted"],
) -> str:
    """Convert the registry visibility to the GQL visibility."""
    try:
        return Visibility[visibility].value
    except LookupError:
        allowed_str = ", ".join(map(repr, (e.name for e in Visibility)))
        raise ValueError(
            f"Invalid visibility: {visibility!r}. Must be one of: {allowed_str}"
        )


def ensure_registry_prefix_on_names(query: Any, in_name: bool = False) -> Any:
    """Traverse the filter to prepend the `name` key value with the registry prefix unless the value is a regex.

    - in_name: True if we are under a "name" key (or propagating from one).

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    if isinstance((txt := query), str):
        if in_name:
            return ensureprefix(txt, REGISTRY_PREFIX)
        return txt
    if isinstance((dct := query), Mapping):
        new_dict = {}
        for key, obj in dct.items():
            if key == "name":
                new_dict[key] = ensure_registry_prefix_on_names(obj, in_name=True)
            elif key == "$regex":
                # For regex operator, we skip transformation of its value.
                new_dict[key] = obj
            else:
                # For any other key, propagate the in_name and skip_transform flags as-is.
                new_dict[key] = ensure_registry_prefix_on_names(obj, in_name=in_name)
        return new_dict
    if isinstance((objs := query), Sequence):
        return list(
            map(lambda x: ensure_registry_prefix_on_names(x, in_name=in_name), objs)
        )
    return query


@lru_cache(maxsize=10)
def fetch_org_entity_from_organization(client: Client, organization: str) -> str:
    """Fetch the org entity from the organization.

    Args:
        client (Client): Graphql client.
        organization (str): The organization to fetch the org entity for.
    """
    query = gql(
        """
        query FetchOrgEntityFromOrganization($organization: String!) {
            organization(name: $organization) {
                    orgEntity {
                        name
                    }
                }
            }
        """
    )
    try:
        response = client.execute(query, variable_values={"organization": organization})
    except Exception as e:
        raise ValueError(
            f"Error fetching org entity for organization: {organization!r}"
        ) from e

    if (
        not (org := response["organization"])
        or not (org_entity := org["orgEntity"])
        or not (org_name := org_entity["name"])
    ):
        raise ValueError(f"Organization entity for {organization!r} not found.")

    return org_name
