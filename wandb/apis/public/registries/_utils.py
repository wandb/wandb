from __future__ import annotations

import logging
from collections.abc import Collection, Iterable
from contextlib import suppress
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import assert_never

from wandb._filters.operators import KEY_TO_OP
from wandb._iterutils import merge_dicts
from wandb._strutils import b64decode_ascii, ensureprefix, repr_join
from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:
    from wandb.apis.public import ArtifactCollection, Registry
    from wandb.apis.public.service_api import ServiceApi

logger = logging.getLogger(__name__)


@pydantic_dataclass(frozen=True, slots=True)
class SearchField:
    name: str  #: The canonical name of the field.
    aliases: tuple[str, ...] = ()  #: Accepted aliases for the field.


def merge_alias_maps(fields: Iterable[SearchField]) -> dict[str, str]:
    """Returns a combined map of all accepted field aliases -> canonical name."""
    # Don't forget to allow the canonical name itself
    return merge_dicts(
        {alias: f.name for alias in (f.name, *f.aliases)} for f in fields
    )


# ------------------------------------------------------------------------------


BASIC_REGISTRIES_FILTER_FIELDS = (
    SearchField("id"),
    SearchField("name"),
    SearchField("entity_id"),
    SearchField("description"),  # Only supported in "basic" search
    SearchField("created_at"),  # Only supported in "basic" search
    SearchField("updated_at"),  # Only supported in "basic" search
)
"""Defines allowed Registries filter fields for "basic" search.

This is relevant for REGISTRY filters passed to:
- Registries(...) ALWAYS, as advanced search applies to versions queries.
- Versions(...) ONLY in "basic" search mode.
"""

ADVANCED_REGISTRIES_FILTER_FIELDS = (
    SearchField("project_id", aliases=["id"]),
    SearchField("name"),
    SearchField("entity_id"),
)
"""Defines allowed Registries filter fields for "advanced" search.

This is relevant for REGISTRY filters passed to:
- Versions(...) ONLY in "advanced" search mode
"""

# ------------------------------------------------------------------------------

BASIC_COLLECTIONS_FILTER_FIELDS = (
    SearchField("artifact_collection_id", aliases=["collection_id", "id"]),
    SearchField("name"),
    SearchField("tag"),
    SearchField("description"),  # Only supported in "basic" search
    SearchField("created_at"),  # Only supported in "basic" search
    SearchField("updated_at"),  # Only supported in "basic" search
)
"""Defines allowed Collections filter fields for "basic" search.

This is relevant for COLLECTION filters passed to:
- Collections(...) ALWAYS, as advanced search applies to versions queries.
- Versions(...) ONLY in "basic" search mode
"""

ADVANCED_COLLECTIONS_FILTER_FIELDS = (
    SearchField("artifact_collection_id", aliases=["collection_id", "id"]),
    SearchField("name", aliases=["collection_name", "artifact_collection_name"]),
    SearchField("tag", aliases=["tags"]),
)
"""Defines allowed Collections filter fields for "advanced" search.

This is relevant for COLLECTION filters passed to:
- Versions(...) ONLY in "advanced" search mode
"""

# ------------------------------------------------------------------------------

BASIC_VERSIONS_FILTER_FIELDS = (
    SearchField("id"),
    SearchField("version"),
    SearchField("tag"),
    SearchField("alias"),
    SearchField("metadata"),
    SearchField("created_at"),
    SearchField("updated_at"),  # Only supported in "basic" search
)
"""Defines allowed Versions filter fields for "basic" search.

This is relevant for VERSION filters passed to:
- Versions(...) ONLY in "basic" search mode
"""

ADVANCED_VERSIONS_FILTER_FIELDS = (
    SearchField("artifact_id", aliases=["id"]),
    SearchField("version", aliases=["version_index"]),
    SearchField("tag", aliases=["tags"]),
    SearchField("alias", aliases=["aliases"]),
    SearchField("metadata", aliases=["artifact_metadata"]),
    SearchField("artifact_created_at", aliases=["created_at"]),
    SearchField("artifact_size"),  # Only supported in "advanced" search
)
"""Defines allowed Versions filter fields for "advanced" search.

This is relevant for VERSION filters passed to:
- Versions(...) ONLY in "advanced" search mode
"""

ADVANCED_VERSIONS_ORDER_FIELDS = (
    SearchField("artifact_created_at", aliases=["created_at"]),
    SearchField("artifact_size"),
    SearchField("acm_created_at", aliases=["linked_at"]),
)
"""Defines allowed Versions order fields for "advanced" search.

This is relevant for VERSION orders passed to:
- Versions(...) ONLY in "advanced" search mode
"""

# ------------------------------------------------------------------------------

BASIC_REGISTRIES_FILTER_ALIASES = merge_alias_maps(BASIC_REGISTRIES_FILTER_FIELDS)
BASIC_COLLECTIONS_FILTER_ALIASES = merge_alias_maps(BASIC_COLLECTIONS_FILTER_FIELDS)
BASIC_VERSIONS_FILTER_ALIASES = merge_alias_maps(BASIC_VERSIONS_FILTER_FIELDS)

ADVANCED_REGISTRIES_FILTER_ALIASES = merge_alias_maps(ADVANCED_REGISTRIES_FILTER_FIELDS)
ADVANCED_COLLECTIONS_FILTER_ALIASES = merge_alias_maps(
    ADVANCED_COLLECTIONS_FILTER_FIELDS
)
ADVANCED_VERSIONS_FILTER_ALIASES = merge_alias_maps(ADVANCED_VERSIONS_FILTER_FIELDS)
ADVANCED_VERSIONS_ORDER_ALIASES = merge_alias_maps(ADVANCED_VERSIONS_ORDER_FIELDS)


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


def decode_project_id(gql_id: str) -> int | None:
    """Returns the int project ID from a base64-encoded GraphQL ID, or None if invalid."""
    with suppress(ValueError, UnicodeDecodeError):
        match b64decode_ascii(gql_id).split(":"):
            case ["ProjectInternalId" | "Project", idx] if idx.isdigit():
                return int(idx)
            case _:
                pass

    logger.warning(f"Invalid project ID: {gql_id!r}")
    return None


def registry_filter_for(obj: Registry | ArtifactCollection) -> dict[str, Any]:
    """Returns a filter for Registry objects derived from a registry-related object."""
    from wandb.apis.public import ArtifactCollection, Registry

    match obj:
        case Registry(internal_id=str(b64_id)) if int_id := decode_project_id(b64_id):
            return {"id": int_id}
        case Registry(full_name=name):
            return {"name": name}

        case ArtifactCollection(project_internal_id=str(b64_id)) if (
            int_id := decode_project_id(b64_id)
        ):
            return {"id": int_id}
        case ArtifactCollection(project=name):
            return {"name": name}

        case _:
            assert_never(obj)


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
    return bool((feats := org.advanced_registry_features) and feats.advanced_search)
