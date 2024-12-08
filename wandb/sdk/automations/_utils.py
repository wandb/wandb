from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast

from pydantic import Json
from pydantic_core import to_json

from ._generated import (
    CreateFilterTriggerInput,
    TriggeredActionConfig,
    TriggeredActionType,
    TriggerScopeType,
)

if TYPE_CHECKING:
    from .automations import ActionInput, NewAutomation

T = TypeVar("T")


def jsonify(obj: T) -> Json[T]:
    """Return the expected JSON serialization of the given object."""
    jsonified = to_json(obj, by_alias=True, round_trip=True).decode("utf8")
    return cast(Json[T], jsonified)


SCOPE_TYPE_MAP: dict[str, TriggerScopeType] = {
    "Project": TriggerScopeType.PROJECT,
    "ArtifactCollection": TriggerScopeType.ARTIFACT_COLLECTION,
    "ArtifactPortfolio": TriggerScopeType.ARTIFACT_COLLECTION,
    "ArtifactSequence": TriggerScopeType.ARTIFACT_COLLECTION,
}
"""Mapping of `__typename`s to automation scope types."""

ACTION_TYPE_MAP: dict[str, TriggeredActionType] = {
    "QueueJobTriggeredAction": TriggeredActionType.QUEUE_JOB,
    "NotificationTriggeredAction": TriggeredActionType.NOTIFICATION,
    "GenericWebhookTriggeredAction": TriggeredActionType.GENERIC_WEBHOOK,
}
"""Mapping of `__typename`s to automation action types."""


def prepare_action_input(obj: ActionInput) -> TriggeredActionConfig:
    """Return a `TriggeredActionConfig` as required in the input schema of CreateFilterTriggerInput."""
    from wandb.sdk.automations.actions import DoLaunchJob, DoNotification, DoWebhook

    if isinstance(obj, DoLaunchJob):
        return TriggeredActionConfig(queue_job_action_input=obj)
    if isinstance(obj, DoNotification):
        return TriggeredActionConfig(notification_action_input=obj)
    if isinstance(obj, DoWebhook):
        return TriggeredActionConfig(generic_webhook_action_input=obj)

    raise TypeError(f"Unsupported action type {type(obj).__qualname__!r}: {obj!r}")


def prepare_create_automation_input(obj: NewAutomation) -> CreateFilterTriggerInput:
    return CreateFilterTriggerInput(
        name=obj.name,
        description=obj.description,
        enabled=obj.enabled,
        client_mutation_id=obj.client_mutation_id,
        # ------------------------------------------------------------------------------
        scope_type=SCOPE_TYPE_MAP[obj.scope.typename__],
        scope_id=obj.scope.id,
        # ------------------------------------------------------------------------------
        triggering_event_type=obj.event.event_type,
        event_filter=obj.event.filter,
        # ------------------------------------------------------------------------------
        triggered_action_type=obj.action.action_type,
        triggered_action_config=prepare_action_input(obj.action),
    )
