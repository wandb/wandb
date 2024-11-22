from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Union

from pydantic import Field, field_validator
from typing_extensions import Annotated

from wandb._pydantic import Base, GQLId, SerializedToJson, Typename

from ._generated import FilterEventFields, TriggerFields, UserFields
from ._validators import validate_scope
from .actions import (
    DoNothing,
    DoNotification,
    DoWebhook,
    LaunchJobAction,
    NoOpAction,
    NotificationAction,
    WebhookAction,
)
from .events import (
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunMetricFilter,
    _WrappedEventFilter,
)
from .scopes import ArtifactCollectionScope, ProjectScope


class FilterEvent(FilterEventFields):
    """A more introspection-friendly representation of a triggering event from a saved automation."""

    typename__: Typename[Literal["FilterEventTriggeringCondition"]]
    filter: SerializedToJson[_WrappedEventFilter | RunMetricFilter]  # type: ignore[assignment]  # GQL schema doesn't define as JSONString

    def __repr_name__(self) -> str:  # type: ignore[override]
        return self.event_type.value


_ScopeT = Annotated[
    Union[ArtifactCollectionScope, ProjectScope],
    Field(discriminator="typename__"),
]
"""Any scope in which an automation can be triggered."""

_EventT = Annotated[
    Union[FilterEvent,],
    Field(discriminator="typename__"),
]
"""Any event that can trigger an automation."""

_ActionT = Annotated[
    Union[
        LaunchJobAction,
        NotificationAction,
        WebhookAction,
        NoOpAction,
    ],
    Field(
        discriminator="typename__",
        alias="triggeredAction",
        validation_alias="triggered_action",
    ),
]
"""Any action that can be triggered by an automation."""


class Automation(TriggerFields):
    """A local instance of a saved W&B automation."""

    id: GQLId

    created_by: UserFields = Field(repr=False, frozen=True)
    created_at: datetime = Field(repr=False, frozen=True)
    updated_at: datetime | None = Field(repr=False, frozen=True)

    name: str
    description: str | None

    scope: _ScopeT  # type: ignore[assignment]
    event: _EventT  # type: ignore[assignment]
    action: _ActionT  # type: ignore[assignment]

    enabled: bool

    @field_validator("scope", mode="before")
    @classmethod
    def _validate_scope(cls, v: Any) -> Any:
        return validate_scope(v)


# Similar type aliases as above, but for input types (for defining new automations)
_ScopeInputT = _ScopeT
_EventInputT = Annotated[
    Union[
        OnLinkArtifact,
        OnAddArtifactAlias,
        OnCreateArtifact,
        OnRunMetric,
    ],
    Field(discriminator="event_type"),
]
_ActionInputT = Annotated[
    Union[
        DoNotification,
        DoWebhook,
        DoNothing,
    ],
    Field(discriminator="action_type"),
]


class NewAutomation(Base):
    """An automation which can hold any of the fields of a NewAutomation, but may not be complete yet."""

    name: str | None = None
    description: str | None = None
    enabled: bool = True

    scope: _ScopeInputT | None = None
    event: _EventInputT | None = None
    action: _ActionInputT | None = None

    @field_validator("scope", mode="before")
    @classmethod
    def _validate_scope(cls, v: Any) -> Any:
        return v if (v is None) else validate_scope(v)


class PreparedAutomation(NewAutomation):
    """A fully defined automation, ready to be sent to the server to create or update it."""

    name: str
    description: str | None = None
    enabled: bool = True

    scope: _ScopeInputT
    event: _EventInputT
    action: _ActionInputT
