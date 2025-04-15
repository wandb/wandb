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

from ._generated import TriggerScopeType
from ._validators import validate_scope

# NOTE: Re-defined publicly with a more readable name for easier access
ScopeType = TriggerScopeType
"""The type of scope that triggers an automation."""


class _BaseScope(GQLBase):
    scope_type: ScopeType


class _ArtifactSequenceScope(_BaseScope, ArtifactSequenceScopeFields):
    """The ID and name of a "sequence"-type ArtifactCollection scope of an automation."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


class _ArtifactPortfolioScope(_BaseScope, ArtifactPortfolioScopeFields):
    """The ID and name of a "portfolio"-type ArtifactCollection scope of an automation."""

    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


# for type annotations
ArtifactCollectionScope = Annotated[
    Union[_ArtifactSequenceScope, _ArtifactPortfolioScope],
    BeforeValidator(validate_scope),
    Field(discriminator="typename__"),
]
"""The ID and name of the ArtifactCollection scope of an automation."""

# for runtime type checks
ArtifactCollectionScopeTypes: tuple[type, ...] = (
    _ArtifactSequenceScope,
    _ArtifactPortfolioScope,
)


class ProjectScope(_BaseScope, ProjectScopeFields):
    """The ID and name of the Project scope of an automation."""

    scope_type: Literal[ScopeType.PROJECT] = ScopeType.PROJECT


# for type annotations
AutomationScope: TypeAlias = Annotated[
    Union[_ArtifactSequenceScope, _ArtifactPortfolioScope, ProjectScope],
    BeforeValidator(validate_scope),
    Field(discriminator="typename__"),
]
# for runtime type checks
AutomationScopeTypes: tuple[type, ...] = get_args(AutomationScope)

# Aliases for naming clarity/consistency
SavedScope: TypeAlias = AutomationScope
InputScope: TypeAlias = AutomationScope

SavedScopeTypes: tuple[type, ...] = get_args(SavedScope)
InputScopeTypes: tuple[type, ...] = get_args(InputScope)
