"""Defined scopes."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from typing_extensions import Annotated

from wandb.sdk.automations._typing import Base64Id, TypenameField
from wandb.sdk.automations.base import Base


class ArtifactPortfolioScope(Base):
    typename__: TypenameField[Literal["ArtifactPortfolio"]]
    id: Base64Id
    name: str


class ArtifactSequenceScope(Base):
    typename__: TypenameField[Literal["ArtifactSequence"]]
    id: Base64Id
    name: str


class ProjectScope(Base):
    typename__: TypenameField[Literal["Project"]]
    id: Base64Id
    name: str


AnyScope = Annotated[
    ArtifactPortfolioScope | ArtifactSequenceScope | ProjectScope,
    Field(discriminator="typename__"),
]
