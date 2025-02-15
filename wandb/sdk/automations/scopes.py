"""Scopes in which a W&B Automation can be triggered."""

from __future__ import annotations

import sys
from typing import Literal, Union

from pydantic import BeforeValidator, Field

from ._generated import GQLBase, GQLId, TriggerScopeType, Typename
from ._validators import validate_scope

if sys.version_info >= (3, 12):
    from typing import Annotated
else:
    from typing_extensions import Annotated

# NOTE: Name shortened for readability and defined publicly for easier access
ScopeType = TriggerScopeType
"""The type of scope that triggers an automation."""


class _Scope(GQLBase):
    typename__: Typename[str]
    scope_type: ScopeType
    id: GQLId
    name: str | None = None


class ArtifactCollectionScope(_Scope):
    """The ID and name of the ArtifactCollection scope of an automation."""

    typename__: Typename[
        Literal["ArtifactSequence", "ArtifactPortfolio", "ArtifactCollection"]
    ] = "ArtifactCollection"
    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION


class ProjectScope(_Scope):
    """The ID and name of the Project scope of an automation."""

    typename__: Typename[Literal["Project"]] = "Project"
    scope_type: Literal[ScopeType.PROJECT] = ScopeType.PROJECT


Annotated[
    Union[ArtifactCollectionScope, ProjectScope],
    Field(discriminator="typename__"),
    BeforeValidator(validate_scope),
]
