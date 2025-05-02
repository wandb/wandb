from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, List, Literal, Mapping, Optional, Sequence

from wandb.sdk.artifacts._validators import (
    REGISTRY_PREFIX,
    validate_artifact_types_list,
)

if TYPE_CHECKING:
    from wandb_gql import Client

from wandb_gql import gql


class _Visibility(str, Enum):
    # names are what users see/pass into Python methods
    # values are what's expected by backend API
    organization = "PRIVATE"
    restricted = "RESTRICTED"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        return next(
            (e for e in cls if e.name == value),
            None,
        )


def _format_gql_artifact_types_input(
    artifact_types: Optional[List[str]] = None,
):
    """Format the artifact types for the GQL input.

    Args:
        artifact_types: The artifact types to add to the registry.

    Returns:
        The artifact types for the GQL input.
    """
    if artifact_types is None:
        return []
    new_types = validate_artifact_types_list(artifact_types)
    return [{"name": type} for type in new_types]


def _gql_to_registry_visibility(
    visibility: str,
) -> Literal["organization", "restricted"]:
    """Convert the GQL visibility to the registry visibility.

    Args:
        visibility: The GQL visibility.

    Returns:
        The registry visibility.
    """
    try:
        return _Visibility(visibility).name
    except ValueError:
        raise ValueError(f"Invalid visibility: {visibility!r} from backend")


def _registry_visibility_to_gql(
    visibility: Literal["organization", "restricted"],
) -> str:
    """Convert the registry visibility to the GQL visibility."""
    try:
        return _Visibility[visibility].value
    except KeyError:
        raise ValueError(
            f"Invalid visibility: {visibility!r}. "
            f"Must be one of: {', '.join(_Visibility.__members__.keys())}"
        )


def _ensure_registry_prefix_on_names(query, in_name=False):
    """Traverse the filter to prepend the `name` key value with the registry prefix unless the value is a regex.

    - in_name: True if we are under a "name" key (or propagating from one).

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    if isinstance((txt := query), str):
        if in_name:
            return txt if txt.startswith(REGISTRY_PREFIX) else f"{REGISTRY_PREFIX}{txt}"
        return txt
    if isinstance((dct := query), Mapping):
        new_dict = {}
        for key, obj in dct.items():
            if key == "name":
                new_dict[key] = _ensure_registry_prefix_on_names(obj, in_name=True)
            elif key == "$regex":
                # For regex operator, we skip transformation of its value.
                new_dict[key] = obj
            else:
                # For any other key, propagate the in_name and skip_transform flags as-is.
                new_dict[key] = _ensure_registry_prefix_on_names(obj, in_name=in_name)
        return new_dict
    if isinstance((objs := query), Sequence):
        return list(
            map(lambda x: _ensure_registry_prefix_on_names(x, in_name=in_name), objs)
        )
    return query


@lru_cache(maxsize=10)
def _fetch_org_entity_from_organization(client: "Client", organization: str) -> str:
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
        if response["organization"] and response["organization"]["orgEntity"]:
            if response["organization"]["orgEntity"]["name"]:
                return response["organization"]["orgEntity"]["name"]
            return ValueError(
                f"Organization entity for organization: {organization} is empty"
            )
        raise ValueError(
            f"Organization entity for organization: {organization} not found"
        )
    except Exception as e:
        raise ValueError(
            f"Error fetching org entity for organization: {organization}"
        ) from e
