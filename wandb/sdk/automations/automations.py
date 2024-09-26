from __future__ import annotations

from datetime import datetime
from typing import Union

from pydantic import AliasChoices, Field
from typing_extensions import Annotated

from wandb.sdk.automations._base import Base
from wandb.sdk.automations._generated.fragments import UserInfo
from wandb.sdk.automations._typing import Base64Id
from wandb.sdk.automations.actions import (
    AnyAction,
    NewNotification,
    NewQueueJob,
    NewWebhook,
)
from wandb.sdk.automations.events import (
    Event,
    NewAddArtifactAlias,
    NewCreateArtifact,
    NewLinkArtifact,
    NewRunMetric,
)
from wandb.sdk.automations.scopes import AnyScope

AnyEvent = Annotated[
    Event,
    Field(
        alias="triggeringCondition",
        validation_alias=AliasChoices("triggeringCondition", "triggering_condition"),
    ),
]


class Automation(Base):
    """A defined W&B automation."""

    id: Base64Id = Field(frozen=True)
    created_by: UserInfo = Field(repr=False, frozen=True)
    created_at: datetime = Field(repr=False, frozen=True)
    updated_at: datetime | None = Field(repr=False, frozen=True)

    name: str
    description: str | None

    scope: AnyScope
    event: AnyEvent
    action: AnyAction

    enabled: bool


AnyNewEvent = Annotated[
    Union[
        NewLinkArtifact,
        NewAddArtifactAlias,
        NewCreateArtifact,
        NewRunMetric,
    ],
    Field(discriminator="event_type"),
]


class NewAutomation(Base):
    """A newly defined automation, prepared to be sent to the server to register it."""

    name: str
    description: str | None = None

    scope: AnyScope
    event: AnyNewEvent
    action: AnyNewAction

    enabled: bool = True

    client_mutation_id: str | None = None


AnyNewAction = Annotated[
    Union[NewQueueJob, NewNotification, NewWebhook],
    Field(discriminator="action_type"),
]
