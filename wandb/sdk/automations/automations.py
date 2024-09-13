from __future__ import annotations

from datetime import datetime

from pydantic import Field, Json

from wandb.sdk.automations._typing import Base64Id
from wandb.sdk.automations._utils import UserInfo
from wandb.sdk.automations.actions import AnyAction
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.events import AnyEvent, Filter, FilterEventType
from wandb.sdk.automations.generated.schema_gen import (
    TriggeredActionConfig,
    TriggeredActionType,
    TriggerScopeType,
)
from wandb.sdk.automations.scopes import AnyScope


class Automation(Base):
    """A defined W&B automation."""

    id: Base64Id

    name: str
    description: str | None

    created_by: UserInfo
    created_at: datetime
    updated_at: datetime | None

    scope: AnyScope
    enabled: bool

    event: AnyEvent
    action: AnyAction


class CreateAutomationInput(Base):
    """A newly defined automation, to be prepared and sent by the client to the server."""

    name: str
    description: str | None
    enabled: bool

    scope_type: TriggerScopeType
    scope_id: Base64Id = Field(alias="scopeID")

    triggering_event_type: FilterEventType
    event_filter: Json[Filter]

    triggered_action_type: TriggeredActionType
    triggered_action_config: TriggeredActionConfig

    client_mutation_id: str | None = None


class DeletedAutomation(Base):
    """Response payload from deleting an automation."""

    success: bool
    client_mutation_id: str | None = None
