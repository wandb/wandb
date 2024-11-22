from __future__ import annotations

import sys
from datetime import datetime
from typing import Literal, Tuple, TypeVar, Union

from pydantic import AliasChoices, Field, Json

from wandb.sdk.automations._base import Base
from wandb.sdk.automations._generated.fragments import (
    FilterEventTriggeringCondition,
    UserInfo,
)
from wandb.sdk.automations._typing import Base64Id, Typename
from wandb.sdk.automations.actions import (
    DoLaunchJob,
    DoNotification,
    DoWebhook,
    LaunchJobAction,
    NotificationAction,
    WebhookAction,
)
from wandb.sdk.automations.events import (
    EventFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunMetricFilter,
)
from wandb.sdk.automations.scopes import ArtifactCollection, Project

if sys.version_info >= (3, 12):
    from typing import Annotated, Self, TypeAlias
else:
    from typing_extensions import Annotated, Self, TypeAlias


class FilterEvent(FilterEventTriggeringCondition):
    """A more introspection-friendly representation of a triggering event from a saved automation."""

    typename__: Typename[Literal["FilterEventTriggeringCondition"]]
    filter: Json[EventFilter | RunMetricFilter]  # type: ignore[assignment]  # GQL schema doesn't define as JSONString

    def __repr_name__(self) -> str:  # type: ignore[override]
        return self.event_type.value


AutomationEvent = Annotated[
    Union[FilterEvent,],
    Field(discriminator="typename__"),
]

AutomationScope = Annotated[
    Union[
        ArtifactCollection,
        Project,
    ],
    Field(discriminator="typename__"),
]

AutomationAction = Annotated[
    Union[
        LaunchJobAction,
        NotificationAction,
        WebhookAction,
    ],
    Field(
        discriminator="typename__",
        serialization_alias="triggeredAction",
        validation_alias=AliasChoices("triggeredAction", "triggered_action"),
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

    scope: AutomationScope
    event: FilterEvent
    action: AutomationAction

    enabled: bool


EventInput = Annotated[
    Union[
        OnLinkArtifact,
        OnAddArtifactAlias,
        OnCreateArtifact,
        OnRunMetric,
    ],
    Field(discriminator="event_type"),
]

ActionInput = Annotated[
    Union[
        DoNotification,
        DoWebhook,
        DoLaunchJob,
    ],
    Field(discriminator="action_type"),
]


EventInputT = TypeVar("EventInputT", bound=EventInput)
ActionInputT = TypeVar("ActionInputT", bound=ActionInput)
EventAndActionInput: TypeAlias = Tuple[EventInputT, ActionInputT]


class NewAutomation(Base):
    """A newly defined automation, prepared to be sent to the server to register it."""

    name: str
    description: str | None = None

    scope: AutomationScope
    event: EventInput
    action: ActionInput

    enabled: bool = True

    client_mutation_id: str | None = None

    @classmethod
    def define(
        cls,
        event_and_action: EventAndActionInput[EventInputT, ActionInputT],
        *,
        name: str,
        description: str | None = None,
        enabled: bool = True,
    ) -> Self:
        event, action = event_and_action
        return cls(
            name=name,
            description=description,
            enabled=enabled,
            scope=event.scope,
            event=event,
            action=action,
        )
