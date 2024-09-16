from __future__ import annotations

from datetime import datetime

from pydantic import Field, Json

from wandb.sdk.automations._typing import Base64Id
from wandb.sdk.automations._utils import UserInfo
from wandb.sdk.automations.actions import ActionType, AnyAction, NewActionConfig
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.events import AnyEvent, EventFilter, EventType
from wandb.sdk.automations.scopes import AnyScope, ScopeType


class Automation(Base):
    """A defined W&B automation."""

    id: Base64Id

    name: str
    description: str | None
    enabled: bool

    created_by: UserInfo = Field(repr=False)
    created_at: datetime = Field(repr=False)
    updated_at: datetime | None = Field(repr=False)

    scope: AnyScope
    event: AnyEvent
    action: AnyAction


class NewAutomation(Base):
    """A newly defined automation, prepared to be sent to the server to register it."""

    name: str
    description: str | None
    enabled: bool = True

    scope_type: ScopeType
    scope_id: Base64Id = Field(alias="scopeID")

    triggering_event_type: EventType
    event_filter: Json[EventFilter]

    triggered_action_type: ActionType
    triggered_action_config: NewActionConfig

    client_mutation_id: str | None = None


class DeletedAutomation(Base):
    """Response payload from deleting an automation."""

    success: bool
    client_mutation_id: str | None = None
