from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from ._generated import (
    CreateFilterTriggerInput,
    GenericWebhookActionInput,
    NotificationActionInput,
    TriggeredActionConfig,
)
from .actions import ActionType
from .scopes import ScopeType

if TYPE_CHECKING:
    from .automations import ActionInput, NewAutomation
    from .events import EventType

T = TypeVar("T")


_SCOPE_TYPE_MAP: dict[str, ScopeType] = {
    "Project": ScopeType.PROJECT,
    "ArtifactCollection": ScopeType.ARTIFACT_COLLECTION,
    "ArtifactPortfolio": ScopeType.ARTIFACT_COLLECTION,
    "ArtifactSequence": ScopeType.ARTIFACT_COLLECTION,
}
"""Mapping of `__typename`s to automation scope types."""


def get_scope_type(obj: Any) -> ScopeType:
    """Discriminator callable to get the scope type from an object."""
    from wandb.apis import public

    # Accept and handle "public API" types that users may already be familiar with
    if isinstance(obj, (public.ArtifactCollection, public.Project)):
        return _SCOPE_TYPE_MAP[type(obj).__name__]

    # ... or decoded JSON dicts
    if isinstance(obj, Mapping) and (typename := obj.get("__typename")):
        return _SCOPE_TYPE_MAP[typename]

    # ... or Pydantic models with a `typename__` attribute
    if isinstance(obj, BaseModel) and (typename := getattr(obj, "typename__", None)):
        return _SCOPE_TYPE_MAP[typename]

    # ... as a last resort, infer from the prefix of the base64-encoded ID
    if isinstance(obj, Mapping) and (id_ := obj.get("id")):
        decoded_id = base64.b64decode(id_).decode("utf-8")
        prefix, *_ = decoded_id.split(":")
        return _SCOPE_TYPE_MAP[prefix]

    raise ValueError(f"Cannot determine scope type of {type(obj)!r} object: {obj!r}")


def get_event_type(obj: Any) -> EventType:
    from .events import (
        EventType,
        OnAddArtifactAlias,
        OnCreateArtifact,
        OnLinkArtifact,
        OnRunMetric,
    )

    if isinstance(obj, OnCreateArtifact):
        return EventType.CREATE_ARTIFACT
    if isinstance(obj, OnLinkArtifact):
        return EventType.LINK_MODEL
    if isinstance(obj, OnAddArtifactAlias):
        return EventType.ADD_ARTIFACT_ALIAS
    if isinstance(obj, OnRunMetric):
        return EventType.RUN_METRIC
    raise ValueError(f"Cannot determine event type of {type(obj)!r} object: {obj!r}")


ACTION_TYPE_MAP: dict[str, ActionType] = {
    "NotificationAction": ActionType.NOTIFICATION,
    "GenericWebhookAction": ActionType.GENERIC_WEBHOOK,
    "QueueJobAction": ActionType.QUEUE_JOB,
}
"""Mapping of GraphQL `__typename`s to automation action types."""


def get_action_type(obj: Any) -> ActionType:
    """Return the `ActionType` associated with the automation ActionInput."""
    if isinstance(obj, NotificationActionInput):
        return ActionType.NOTIFICATION
    if isinstance(obj, GenericWebhookActionInput):
        return ActionType.GENERIC_WEBHOOK
    raise TypeError(f"Unsupported action type {obj.__qualname__!r}: {obj!r}")


def prepare_action_config(obj: ActionInput) -> TriggeredActionConfig:
    """Return a `TriggeredActionConfig` as required in the input schema of CreateFilterTriggerInput."""
    if isinstance(obj, NotificationActionInput):
        return TriggeredActionConfig(notification_action_input=obj)
    if isinstance(obj, GenericWebhookActionInput):
        return TriggeredActionConfig(generic_webhook_action_input=obj)
    raise TypeError(f"Unsupported action type {type(obj).__qualname__!r}: {obj!r}")


def prepare_create_automation_input(obj: NewAutomation) -> CreateFilterTriggerInput:
    input_obj = CreateFilterTriggerInput(
        name=obj.name,
        description=obj.description,
        enabled=obj.enabled,
        client_mutation_id=obj.client_mutation_id,
        # ------------------------------------------------------------------------------
        scope_type=get_scope_type(obj.scope),
        scope_id=obj.scope.id,
        # ------------------------------------------------------------------------------
        triggering_event_type=get_event_type(obj.event),
        event_filter=obj.event.filter,
        # ------------------------------------------------------------------------------
        triggered_action_type=get_action_type(obj.action),
        triggered_action_config=prepare_action_config(obj.action),
    )
    return input_obj
