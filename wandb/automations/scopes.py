"""Scopes in which a W&B Automation can be triggered."""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BeforeValidator, Field
from typing_extensions import Annotated, TypeAlias, get_args

from wandb._pydantic import GQLBase

from ._generated import (
    ArtifactPortfolioScopeFields,
    ArtifactSequenceScopeFields,
    ProjectScopeFields,
)
from ._validators import LenientStrEnum, parse_scope


# NOTE: Re-defined publicly with a more readable name for easier access
class ScopeType(LenientStrEnum):
    """The kind of scope that triggers an automation."""

    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"
    PROJECT = "PROJECT"

    # Server-side, a registry is treated as a specialized Project at the DB level,
    # so a registry-scoped automation is equivalent to a PROJECT scope.
    REGISTRY = PROJECT


class _BaseScope(GQLBase, extra="ignore"):
    scope_type: Annotated[ScopeType, Field(frozen=True)]


class _ArtifactSequenceScope(_BaseScope, ArtifactSequenceScopeFields):
    """An automation scope defined by a specific `ArtifactSequence`."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


class _ArtifactPortfolioScope(_BaseScope, ArtifactPortfolioScopeFields):
    """Automation scope defined by an `ArtifactPortfolio` (e.g. a registry collection)."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


# for type annotations
ArtifactCollectionScope = Annotated[
    Union[_ArtifactSequenceScope, _ArtifactPortfolioScope],
    BeforeValidator(parse_scope),
    Field(discriminator="typename__"),
]
"""An automation scope defined by a specific `ArtifactCollection`."""

# for runtime type checks
ArtifactCollectionScopeTypes: tuple[type, ...] = get_args(
    ArtifactCollectionScope.__origin__  # type: ignore[attr-defined]
)


class ProjectScope(_BaseScope, ProjectScopeFields):
    """An automation scope defined by a specific `Project`."""

    scope_type: Literal[ScopeType.PROJECT] = ScopeType.PROJECT


class RegistryScope(ProjectScope):
    """An automation scope defined by a specific `Registry`."""

    scope_type: Literal[ScopeType.REGISTRY] = ScopeType.REGISTRY  # type: ignore[assignment]
    name: Annotated[str, Field(validation_alias="full_name")]


# for type annotations
AutomationScope: TypeAlias = Annotated[
    Union[ProjectScope, ArtifactCollectionScope],
    BeforeValidator(parse_scope),
    Field(discriminator="typename__"),
]

__all__ = [
    "ScopeType",
    "ArtifactCollectionScope",
    "ProjectScope",
    "RegistryScope",
]
