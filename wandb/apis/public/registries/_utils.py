from __future__ import annotations

from enum import Enum
from functools import lru_cache, partial
from typing import TYPE_CHECKING, Any, Collection

from wandb._strutils import ensureprefix
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX, validate_artifact_types

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
        """Convert a visibility string (e.g. user-provided or python default value) to a Visibility enum."""
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
    if artifact_types:
        return [{"name": typ} for typ in validate_artifact_types(artifact_types)]
    return None


def ensure_registry_prefix_on_names(query: Any, in_name: bool = False) -> Any:
    """Traverse the filter to prepend the `name` key value with the registry prefix unless the value is a regex.

    - in_name: True if we are under a "name" key (or propagating from one).

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    if isinstance((txt := query), str):
        return ensureprefix(txt, REGISTRY_PREFIX) if in_name else txt
    if isinstance((dct := query), dict):
        new_dict = {}
        for key, obj in dct.items():
            if key == "$regex":
                # For regex operator, we skip transformation of its value.
                new_dict[key] = obj
            elif key == "name":
                new_dict[key] = ensure_registry_prefix_on_names(obj, in_name=True)
            else:
                # For any other key, propagate the in_name and skip_transform flags as-is.
                new_dict[key] = ensure_registry_prefix_on_names(obj, in_name=in_name)
        return new_dict
    if isinstance((seq := query), (list, tuple)):
        return list(map(partial(ensure_registry_prefix_on_names, in_name=in_name), seq))
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
