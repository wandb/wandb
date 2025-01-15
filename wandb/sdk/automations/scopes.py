"""Scopes in which a W&B Automation can be triggered."""

from __future__ import annotations

from typing import Literal

from ._generated import GQLBase, GQLId, TriggerScopeType, Typename

# NOTE: Name shortened for readability and defined publicly for easier access
ScopeType = TriggerScopeType
"""The type of scope that triggers an automation."""


class _ScopeInfo(GQLBase):
    typename__: Typename[str]
    id: GQLId
    name: str | None = None


class ArtifactCollectionScope(_ScopeInfo):
    """The ID and name of the ArtifactCollection scope of an automation."""

    typename__: Typename[
        Literal["ArtifactSequence", "ArtifactPortfolio", "ArtifactCollection"]
    ] = "ArtifactCollection"


class ProjectScope(_ScopeInfo):
    """The ID and name of the Project scope of an automation."""

    typename__: Typename[Literal["Project"]] = "Project"
