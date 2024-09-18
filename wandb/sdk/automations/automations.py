from __future__ import annotations

from datetime import datetime

from pydantic import Field, Json

from wandb.sdk.automations._typing import Base64Id
from wandb.sdk.automations._utils import UserInfo, jsonify
from wandb.sdk.automations.actions import (
    ActionType,
    AnyAction,
    AnyNewAction,
    NewActionConfig,
    NewNotification,
    NewNotificationConfig,
    NewQueueJob,
    NewQueueJobConfig,
    NewWebhook,
    NewWebhookConfig,
)
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.events import (
    AnyEvent,
    AnyNewEvent,
    EventFilter,
    EventTrigger,
    EventType,
)
from wandb.sdk.automations.schemas_gen import CreateFilterTriggerInput
from wandb.sdk.automations.scopes import AnyScope, ScopeType


class Automation(Base):
    """A defined W&B automation."""

    id: Base64Id

    name: str
    description: str | None

    created_by: UserInfo = Field(repr=False)
    created_at: datetime = Field(repr=False)
    updated_at: datetime | None = Field(repr=False)

    scope: AnyScope
    event: AnyEvent
    action: AnyAction

    enabled: bool


class NewAutomation(Base):
    """A newly defined automation, prepared to be sent to the server to register it."""

    name: str
    description: str | None
    enabled: bool = True

    scope: AnyScope
    event: AnyNewEvent
    action: AnyNewAction

    client_mutation_id: str | None = None

    def to_create_payload(self) -> CreateFilterTriggerInput:
        return CreateFilterTriggerInput(
            **self.model_dump(exclude={"scope", "event", "action"}),
            # ------------------------------------------------------------------------------
            scope_type=self.scope.scope_type.value,
            scope_id=self.scope.id,
            # ------------------------------------------------------------------------------
            triggering_event_type=self.event.event_type.value,
            event_filter=jsonify(self.event.filter),
            # ------------------------------------------------------------------------------
            triggered_action_type=self.action.action_type.value,
            triggered_action_config=_to_triggered_action_config(self.action),
        )


class DeletedAutomation(Base):
    """Response payload from deleting an automation."""

    success: bool
    client_mutation_id: str | None = None


def _to_triggered_action_config(action: AnyNewAction) -> NewActionConfig:
    """Return a `TriggeredActionConfig` as required in the input schema of CreateFilterTriggerInput."""
    match action:
        case NewQueueJob():
            return NewQueueJobConfig(queue_job_action_input=action)
        case NewNotification():
            return NewNotificationConfig(notification_action_input=action)
        case NewWebhook():
            return NewWebhookConfig(generic_webhook_action_input=action)
        case _:
            raise TypeError(
                f"Unknown action type {type(action).__qualname__!r}: {action!r}"
            )
