from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, TypeAdapter
from typing_extensions import Annotated

from wandb import util
from wandb.sdk.automations._typing import Base64Id, TypenameField
from wandb.sdk.automations.actions import AnyAction
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.events import AnyEvent

reset_path = util.vendor_setup()


# ------------------------------------------------------------------------------
class User(Base):
    id: Base64Id
    username: str


# Scopes
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


class ReadAutomation(Base):
    """A defined W&B automation."""

    id: Base64Id

    name: str
    description: str | None

    created_by: User
    created_at: datetime
    updated_at: datetime | None

    scope: AnyScope
    enabled: bool

    event: AnyEvent
    action: AnyAction


class CreateAutomation(Base):
    """A newly defined automation, to be prepared and sent by the client to the server."""

    name: str
    description: str | None

    scope: AnyScope
    enabled: bool

    event: AnyEvent
    action: AnyAction


ReadAutomationsAdapter = TypeAdapter(list[ReadAutomation])
