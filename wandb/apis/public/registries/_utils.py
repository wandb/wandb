from __future__ import annotations

import re
from collections.abc import Collection
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar, overload

from pydantic.dataclasses import dataclass as pydantic_dataclass

from wandb._strutils import ensureprefix, repr_join

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi


T = TypeVar("T")


@pydantic_dataclass(frozen=True, slots=True)
class OrderArg:
    """A callable validator that checks and normalizes `order` paginator arguments."""

    _REGEX: ClassVar[re.Pattern[str]] = re.compile(r"^(\+|\-)?(\w+)$", flags=re.ASCII)

    allowed: frozenset[str] | None = None
    """The allowed field names. If None, all fields are allowed."""

    def __call__(self, order: str) -> str:
        # Parse the `order` string into its components
        if (match := self._REGEX.match(order)) is None:
            raise ValueError(f"Invalid order field: {order!r}")

        # Normalize
        sign = match.group(1) or "+"
        name = match.group(2).lower()

        # Check if the field name is allowed
        if (allowed := self.allowed) and (name not in allowed):
            msg = f"Invalid order field {name!r}, must be one of: {repr_join(sorted(allowed))}"
            raise ValueError(msg)

        return f"{sign}{name}"


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
def prepare_registry_filter(query: list[T] | tuple[T]) -> list[T]: ...
@overload
def prepare_registry_filter(query: T) -> T: ...


def prepare_registry_filter(query: Any) -> Any:
    """Normalize a registry filter as a JSON-serializable GraphQL input.

    Recursively prepend the registry prefix under "name" keys, excluding regex ops.

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    match query:
        case dict() as dct:
            return {
                k: (_prefix_reg_names(v) if k == "name" else prepare_registry_filter(v))
                for k, v in dct.items()
            }
        case list() | tuple() as seq:
            return list(map(prepare_registry_filter, seq))
        case _:
            return query


def _prefix_reg_names(query: Any) -> Any:
    """Under a "name" key, prefix names with 'wandb-registry-', skipping $regex ops."""
    from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

    match query:
        case str() as txt:
            return ensureprefix(txt, REGISTRY_PREFIX)
        case dict() as dct:
            # For regex operator, we skip transformation of its value.
            return {
                k: (v if k == "$regex" else _prefix_reg_names(v))
                for k, v in dct.items()
            }
        case list() | tuple() as seq:
            return list(map(_prefix_reg_names, seq))
        case _:
            return query


def prepare_collection_filter(query: T) -> T:
    """Normalize a collection filter as a JSON-serializable GraphQL input."""
    return query  # TODO: Add validation for allowed field names


def prepare_version_filter(query: T) -> T:
    """Normalize an artifact version filter as a JSON-serializable GraphQL input."""
    return query  # TODO: Add validation for allowed field names


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
