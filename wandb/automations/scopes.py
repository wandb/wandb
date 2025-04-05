"""Scopes in which a W&B Automation can be triggered."""

from __future__ import annotations

from typing import Literal, Optional, Union

from typing_extensions import TypeAlias, get_args

from wandb._pydantic import GQLBase, GQLId, Typename

from ._generated import TriggerScopeType

# NOTE: Name shortened for readability and defined publicly for easier access
ScopeType = TriggerScopeType
"""The type of scope that triggers an automation."""


class _BaseScope(GQLBase):
    typename__: Typename[str]
    scope_type: ScopeType
    id: GQLId
    name: Optional[str] = None


class ArtifactCollectionScope(_BaseScope):
    """The ID and name of the ArtifactCollection scope of an automation."""

    typename__: Typename[
        Literal["ArtifactSequence", "ArtifactPortfolio", "ArtifactCollection"]
    ] = "ArtifactCollection"
    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


class ProjectScope(_BaseScope):
    """The ID and name of the Project scope of an automation."""

    typename__: Typename[Literal["Project"]] = "Project"
    scope_type: Literal[ScopeType.PROJECT] = ScopeType.PROJECT


# for type annotations
SavedScope: TypeAlias = Union[ArtifactCollectionScope, ProjectScope]
InputScope: TypeAlias = SavedScope  # Same thing, just named for clarity
# for runtime type checks
SavedScopeTypes: tuple[type, ...] = get_args(SavedScope)
InputScopeTypes: tuple[type, ...] = get_args(InputScope)
