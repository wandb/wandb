"""Scopes in which a W&B Automation can be triggered."""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BeforeValidator, Field
from typing_extensions import Annotated, TypeAlias, get_args

from wandb._pydantic import GQLBase
from wandb.automations._generated import (
    ArtifactPortfolioScopeFields,
    ArtifactSequenceScopeFields,
    ProjectScopeFields,
)

from ._validators import LenientStrEnum, to_scope


# NOTE: Re-defined publicly with a more readable name for easier access
class ScopeType(LenientStrEnum):
    """The kind of scope that triggers an automation."""

    PROJECT = "PROJECT"
    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"


class _BaseScope(GQLBase):
    scope_type: Annotated[ScopeType, Field(frozen=True)]


class _ArtifactSequenceScope(_BaseScope, ArtifactSequenceScopeFields):
    """An automation scope defined by a specific `ArtifactSequence`."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


class _ArtifactPortfolioScope(_BaseScope, ArtifactPortfolioScopeFields):
    """An automation scope defined by a specific `ArtifactPortfolio` (e.g. a registry collection)."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


# for type annotations
ArtifactCollectionScope = Annotated[
    Union[_ArtifactSequenceScope, _ArtifactPortfolioScope],
    BeforeValidator(to_scope),
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


# for type annotations
AutomationScope: TypeAlias = Annotated[
    Union[_ArtifactSequenceScope, _ArtifactPortfolioScope, ProjectScope],
    BeforeValidator(to_scope),
    Field(discriminator="typename__"),
]
# for runtime type checks
AutomationScopeTypes: tuple[type, ...] = get_args(AutomationScope.__origin__)  # type: ignore[attr-defined]


__all__ = [
    "ScopeType",
    "ArtifactCollectionScope",
    "ProjectScope",
]
