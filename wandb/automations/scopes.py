"""Scopes in which a W&B Automation can be triggered."""

from __future__ import annotations

from typing import Annotated, Literal, TypeVar

from pydantic import BeforeValidator, Discriminator, Field

from wandb._pydantic import GQLBase

from ._generated import (
    ArtifactPortfolioScopeFields,
    ArtifactSequenceScopeFields,
    EntityScopeFields,
    ProjectScopeFields,
)
from ._validators import LenientStrEnum, parse_scope


# NOTE: Re-defined publicly with a more readable name for easier access
class ScopeType(LenientStrEnum):
    """The kind of scope that triggers an automation."""

    PROJECT = "PROJECT"
    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"
    ENTITY = "ENTITY"


class _EntityType(LenientStrEnum):
    """The backend entity type."""

    PERSONAL = "personal"
    TEAM = "team"
    ORGANIZATION = "organization"


class _BaseScope(GQLBase):
    scope_type: Annotated[ScopeType, Field(frozen=True)]


_ScopeT = TypeVar("_ScopeT", bound=_BaseScope)

ScopeField = Annotated[
    _ScopeT,
    BeforeValidator(parse_scope),
    Discriminator("typename__"),
]


class _ArtifactSequenceScope(_BaseScope, ArtifactSequenceScopeFields):
    """An automation scope defined by a specific `ArtifactSequence`."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


class _ArtifactPortfolioScope(_BaseScope, ArtifactPortfolioScopeFields):
    """Automation scope defined by an `ArtifactPortfolio` (e.g. a registry collection)."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


# for type annotations
ArtifactCollectionScope = ScopeField[_ArtifactSequenceScope | _ArtifactPortfolioScope,]
"""An automation scope defined by a specific `ArtifactCollection`."""

# for runtime type checks
ArtifactCollectionScopeTypes = ArtifactCollectionScope.__origin__  # type: ignore[attr-defined]


class ProjectScope(_BaseScope, ProjectScopeFields):
    """An automation scope defined by a specific `Project`."""

    scope_type: Literal[ScopeType.PROJECT] = ScopeType.PROJECT


class TeamScope(_BaseScope, EntityScopeFields):
    """An automation scope defined by a team entity."""

    scope_type: Literal[ScopeType.ENTITY] = ScopeType.ENTITY
    entity_type: Literal[_EntityType.TEAM] = _EntityType.TEAM


class OrgScope(_BaseScope, EntityScopeFields):
    """An automation scope defined by an org entity."""

    scope_type: Literal[ScopeType.ENTITY] = ScopeType.ENTITY
    entity_type: Literal[_EntityType.ORGANIZATION] = _EntityType.ORGANIZATION


EntityScope = Annotated[
    TeamScope | OrgScope,
    BeforeValidator(parse_scope),
    Discriminator("entity_type"),
]
"""An automation scope defined by a team or org `Entity`."""


# for type annotations
AutomationScope = ScopeField[
    _ArtifactSequenceScope | _ArtifactPortfolioScope | ProjectScope | EntityScope,
]
# for runtime type checks
AutomationScopeTypes = AutomationScope.__origin__  # type: ignore[attr-defined]

__all__ = [
    "ScopeType",
    "ArtifactCollectionScope",
    "ProjectScope",
    "TeamScope",
    "OrgScope",
    "EntityScope",
]
