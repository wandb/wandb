from __future__ import annotations

import sys
from datetime import datetime
from typing import Literal, Union

from pydantic import AliasChoices, Discriminator, Field, Tag

from wandb.sdk.automations._utils import get_scope_type

from ._base import Base, Base64Id, SerializedToJson, Typename
from ._generated import FilterEventFields, UserInfo
from .actions import (
    DoNotification,
    DoWebhook,
    LaunchJobAction,
    NotificationAction,
    WebhookAction,
)
from .events import (
    EventFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunMetricFilter,
)
from .scopes import ArtifactCollectionScope, ProjectScope, ScopeType

if sys.version_info >= (3, 12):
    from typing import Annotated, Self
else:
    from typing_extensions import Annotated, Self


class FilterEvent(FilterEventFields):
    """A more introspection-friendly representation of a triggering event from a saved automation."""

    typename__: Typename[Literal["FilterEventTriggeringCondition"]]
    filter: SerializedToJson[EventFilter | RunMetricFilter | str]  # type: ignore[assignment]  # GQL schema doesn't define as JSONString

    def __repr_name__(self) -> str:  # type: ignore[override]
        return self.event_type.value


AutomationEvent = Annotated[
    Union[FilterEvent,],
    Field(discriminator="typename__"),
]

AutomationScope = Annotated[
    Union[
        Annotated[ArtifactCollectionScope, Tag(ScopeType.ARTIFACT_COLLECTION)],
        Annotated[ProjectScope, Tag(ScopeType.PROJECT)],
    ],
    Discriminator(get_scope_type),
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
    event: AutomationEvent
    action: AutomationAction

    enabled: bool


EventInput = Union[
    OnLinkArtifact,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnRunMetric,
]

ActionInput = Union[
    DoNotification,
    DoWebhook,
]


class PartialNewAutomation(Base):
    """An automation which can hold any of the fields of a NewAutomation, but may not be complete yet."""

    name: str | None = None
    description: str | None = None
    enabled: bool | None = None

    scope: AutomationScope | None = None
    event: EventInput | None = None
    action: ActionInput | None = None

    client_mutation_id: str | None = None


class NewAutomation(Base):
    """A newly defined automation, prepared to be sent to the server to register it."""

    name: str
    description: str | None = None
    enabled: bool = True

    scope: AutomationScope
    event: EventInput
    action: ActionInput

    client_mutation_id: str | None = None

    @classmethod
    def define(
        cls,
        obj: NewAutomation | PartialNewAutomation,
        *,
        name: str,
        description: str | None = None,
        enabled: bool = True,
    ) -> Self:
        return cls.model_validate(
            obj.model_copy(
                update=dict(name=name, description=description, enabled=enabled)
            )
        )
