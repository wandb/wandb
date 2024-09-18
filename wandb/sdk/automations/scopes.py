"""Defined scopes."""

from __future__ import annotations

from enum import StrEnum, global_enum
from typing import Literal

from pydantic import Field
from pydantic._internal import _repr
from typing_extensions import Annotated

from wandb.sdk.automations._typing import Base64Id, Typename
from wandb.sdk.automations.base import Base


@global_enum
class ScopeType(StrEnum):
    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"
    PROJECT = "PROJECT"


ARTIFACT_COLLECTION = ScopeType.ARTIFACT_COLLECTION
PROJECT = ScopeType.PROJECT


class BaseScope(Base):
    """Base class for automation scopes."""

    scope_type: ScopeType = Field(repr=False)

    def __repr_name__(self) -> str:
        return self.scope_type.value

    def __repr_args__(self) -> _repr.ReprArgs:
        if hasattr(self, "name"):
            yield "name", self.name


class ArtifactCollectionScope(BaseScope):
    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ARTIFACT_COLLECTION

    typename__: Typename[
        Literal["ArtifactSequence", "ArtifactPortfolio", "ArtifactCollection"]
    ] = "ArtifactCollection"
    id: Base64Id
    name: str | None = None


class ProjectScope(BaseScope):
    scope_type: Literal[ScopeType.PROJECT] = PROJECT

    typename__: Typename[Literal["Project"]] = "Project"
    id: Base64Id
    name: str | None = None


# AnyScope = ArtifactCollectionScope | ProjectScope
AnyScope = Annotated[
    ArtifactCollectionScope | ProjectScope,
    Field(discriminator="typename__"),
]
