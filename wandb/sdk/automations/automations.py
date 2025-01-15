from __future__ import annotations

import sys
from datetime import datetime
from typing import Literal, Union

from pydantic import Discriminator, Field, Tag

from wandb.sdk.automations._utils import get_scope_type

from ._generated import (
    Base,
    FilterEventFields,
    GQLId,
    SerializedToJson,
    Typename,
    UserFields,
)
from .actions import (
    DoNothing,
    DoNotification,
    DoWebhook,
    LaunchJobAction,
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
from .scopes import ArtifactCollectionScope, ProjectScope, ScopeType

if sys.version_info >= (3, 12):
    from typing import Annotated
else:
    from typing_extensions import Annotated


class FilterEvent(FilterEventFields):
    """A more introspection-friendly representation of a triggering event from a saved automation."""

    typename__: Typename[Literal["FilterEventTriggeringCondition"]]
    filter: SerializedToJson[_WrappedEventFilter | RunMetricFilter | str]  # type: ignore[assignment]  # GQL schema doesn't define as JSONString

    def __repr_name__(self) -> str:  # type: ignore[override]
        return self.event_type.value


_ScopeT = Annotated[
    Union[
        Annotated[ArtifactCollectionScope, Tag(ScopeType.ARTIFACT_COLLECTION)],
        Annotated[ProjectScope, Tag(ScopeType.PROJECT)],
    ],
    Discriminator(get_scope_type),
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
    ],
    Field(
        discriminator="typename__",
        alias="triggeredAction",
        validation_alias="triggered_action",
    ),
]
"""Any action that can be triggered by an automation."""


class Automation(Base):
    """A local instance of a saved W&B automation."""

    id: GQLId = Field(frozen=True)
    created_by: UserFields = Field(repr=False, frozen=True)
    created_at: datetime = Field(repr=False, frozen=True)
    updated_at: datetime | None = Field(repr=False, frozen=True)

    name: str
    description: str | None

    scope: _ScopeT
    event: _EventT
    action: _ActionT

    enabled: bool


# Similar type aliases as above, but for input types (for defining new automations)
_ScopeInputT = _ScopeT
_EventInputT = Union[
    OnLinkArtifact,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnRunMetric,
]
_ActionInputT = Union[
    DoNotification,
    DoWebhook,
    DoNothing,
]


class NewAutomation(Base):
    """An automation which can hold any of the fields of a NewAutomation, but may not be complete yet."""

    name: str | None = None
    description: str | None = None
    enabled: bool = True

    scope: _ScopeInputT | None = None
    event: _EventInputT | None = None
    action: _ActionInputT | None = None

    client_mutation_id: str | None = None


class PreparedAutomation(NewAutomation):
    """A fully defined automation, ready to be sent to the server to register it."""

    name: str
    description: str | None = None
    enabled: bool = True

    scope: _ScopeInputT
    event: _EventInputT
    action: _ActionInputT

    client_mutation_id: str | None = None
