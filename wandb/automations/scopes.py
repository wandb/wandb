"""Scopes in which a W&B Automation can be triggered."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Discriminator, Field, Tag

from wandb._pydantic import GQLBase

from ._generated import (
    ArtifactPortfolioScopeFields,
    ArtifactSequenceScopeFields,
    EntityScopeFields,
    ProjectScopeFields,
)
from ._validators import LenientStrEnum, parse_scope, payload_typename


# NOTE: Re-defined publicly with a more readable name for easier access
class ScopeType(LenientStrEnum):
    """The kind of scope that triggers an automation."""

    PROJECT = "PROJECT"
    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"
    ENTITY = "ENTITY"


class _BaseScope(GQLBase, extra="ignore"):
    scope_type: Annotated[ScopeType, Field(frozen=True)]


class _ArtifactSequenceScope(_BaseScope, ArtifactSequenceScopeFields):
    """A scope defined by an ArtifactSequence."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


class _ArtifactPortfolioScope(_BaseScope, ArtifactPortfolioScopeFields):
    """A scope defined by an ArtifactPortfolio, usually a registry collection."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


# for type annotations
ArtifactCollectionScope = Annotated[
    _ArtifactSequenceScope | _ArtifactPortfolioScope,
    BeforeValidator(parse_scope),
    Discriminator("typename__"),
]
"""Type hint for a scope defined by an ArtifactCollection."""

# for runtime type checks
ArtifactCollectionScopeTypes = ArtifactCollectionScope.__origin__  # type: ignore[attr-defined]


class ProjectScope(_BaseScope, ProjectScopeFields):
    """A scope defined by a Project."""

    scope_type: Literal[ScopeType.PROJECT] = ScopeType.PROJECT
    is_registry: Literal[False] = False


class RegistryScope(_BaseScope, ProjectScopeFields):
    """A scope defined by a Registry."""

    # Registries are represented as projects server-side.
    scope_type: Literal[ScopeType.PROJECT] = ScopeType.PROJECT
    is_registry: Literal[True] = True
    name: Annotated[str, Field(validation_alias="full_name")]


_RegistryOrProjectScope = Annotated[
    RegistryScope | ProjectScope,
    Discriminator("is_registry"),
    BeforeValidator(parse_scope),
]
"""Type hint for a scope defined by a registry or project."""


class TeamScope(_BaseScope, EntityScopeFields):
    """A scope defined by a team Entity."""

    scope_type: Literal[ScopeType.ENTITY] = ScopeType.ENTITY
    entity_type: Literal["team"] = "team"


class OrgScope(_BaseScope, EntityScopeFields):
    """A scope defined by an org Entity."""

    scope_type: Literal[ScopeType.ENTITY] = ScopeType.ENTITY
    entity_type: Literal["organization"] = "organization"


EntityScope = Annotated[
    TeamScope | OrgScope,
    BeforeValidator(parse_scope),
    Discriminator("entity_type"),
]
"""Type hint for a scope defined by a team or org Entity."""


class SavedUnknownScope(GQLBase, extra="allow"):
    """A saved automation scope whose GraphQL type this SDK version does not model."""

    typename__: Annotated[str, Field(alias="__typename")] = "UnknownScope"


AutomationScope = Annotated[
    ArtifactCollectionScope | _RegistryOrProjectScope | EntityScope,
    BeforeValidator(parse_scope),
    Discriminator("typename__"),
]
"""Type hint for any allowed scope for an automation."""

_KNOWN_SCOPE_TYPENAMES = frozenset(
    {
        "ArtifactSequence",
        "ArtifactPortfolio",
        "Project",
        "Entity",
    }
)
_UNKNOWN_SCOPE_TAG = "unknown"


def _saved_scope_discriminator(v: Any) -> str:
    t = payload_typename(v)
    if t is None or t in _KNOWN_SCOPE_TYPENAMES:
        return "known"
    return _UNKNOWN_SCOPE_TAG


SavedTriggerScope = Annotated[
    Annotated[AutomationScope, Tag("known")]
    | Annotated[SavedUnknownScope, Tag(_UNKNOWN_SCOPE_TAG)],
    Discriminator(_saved_scope_discriminator),
]

# for runtime type checks
AutomationScopeTypes = AutomationScope.__origin__  # type: ignore[attr-defined]

__all__ = [
    "ScopeType",
    "ArtifactCollectionScope",
    "ProjectScope",
    "RegistryScope",
    "TeamScope",
    "OrgScope",
    "EntityScope",
]
