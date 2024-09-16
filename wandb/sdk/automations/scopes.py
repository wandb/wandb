"""Defined scopes."""

from __future__ import annotations

from enum import StrEnum, global_enum
from typing import Literal

from pydantic import Field
from typing_extensions import Annotated

from wandb.sdk.automations._typing import Base64Id, TypenameField
from wandb.sdk.automations.base import Base


@global_enum
class ScopeType(StrEnum):
    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"
    PROJECT = "PROJECT"


ARTIFACT_COLLECTION = ScopeType.ARTIFACT_COLLECTION
PROJECT = ScopeType.PROJECT


class BaseScope(Base):
    """Base class for automation scopes."""

    scope_type: ScopeType

    def __repr_name__(self) -> str:
        return self.scope_type.value


class ArtifactCollectionScope(Base):
    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.ARTIFACT_COLLECTION

    typename__: TypenameField[Literal["ArtifactSequence", "ArtifactPortfolio"]]
    id: Base64Id
    name: str


class ProjectScope(Base):
    scope_type: Literal[ScopeType.ARTIFACT_COLLECTION] = ScopeType.PROJECT

    typename__: TypenameField[Literal["Project"]]
    id: Base64Id
    name: str


AnyScope = Annotated[
    ArtifactCollectionScope | ProjectScope,
    Field(discriminator="typename__"),
]
