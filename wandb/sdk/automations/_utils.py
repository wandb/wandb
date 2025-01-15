from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from ._generated import (
    CreateFilterTriggerInput,
    GenericWebhookActionInput,
    NoOpTriggeredActionInput,
    NotificationActionInput,
    TriggeredActionConfig,
)
from .actions import ActionType
from .scopes import ScopeType, _ScopeInfo

if TYPE_CHECKING:
    from .automations import NewAutomation, PreparedAutomation
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
    if isinstance(obj, _ScopeInfo) or hasattr(obj, "typename__"):
        return _SCOPE_TYPE_MAP[obj.typename__]

    # ... as a last resort, infer from the prefix of the base64-encoded ID
    if isinstance(obj, Mapping) and (id_ := obj.get("id")):
        decoded_id = base64.b64decode(id_).decode("utf-8")
        type_name, *_ = decoded_id.split(":")
        return _SCOPE_TYPE_MAP[type_name]

    raise ValueError(f"Cannot determine scope type of {type(obj)!r} object")


def get_event_type(cls: type[Any]) -> EventType:
    from .events import (
        EventType,
        OnAddArtifactAlias,
        OnCreateArtifact,
        OnLinkArtifact,
        OnRunMetric,
    )

    if issubclass(cls, OnCreateArtifact):
        return EventType.CREATE_ARTIFACT
    if issubclass(cls, OnLinkArtifact):
        return EventType.LINK_MODEL
    if issubclass(cls, OnAddArtifactAlias):
        return EventType.ADD_ARTIFACT_ALIAS
    if issubclass(cls, OnRunMetric):
        return EventType.RUN_METRIC
    raise ValueError(f"Cannot determine event type of {cls!r} object")


ACTION_TYPE_MAP: dict[str, ActionType] = {
    "NotificationAction": ActionType.NOTIFICATION,
    "GenericWebhookAction": ActionType.GENERIC_WEBHOOK,
    "QueueJobAction": ActionType.QUEUE_JOB,
}
"""Mapping of GraphQL `__typename`s to automation action types."""


def get_action_type(cls: type[Any]) -> ActionType:
    """Return the `ActionType` associated with the automation ActionInput."""
    if issubclass(cls, NotificationActionInput):
        return ActionType.NOTIFICATION
    if issubclass(cls, GenericWebhookActionInput):
        return ActionType.GENERIC_WEBHOOK
    if issubclass(cls, NoOpTriggeredActionInput):
        return ActionType.NO_OP
    raise ValueError(f"Cannot determine action type of {cls!r} object")


_ACTION_CONFIG_KEYS: dict[ActionType, str] = {
    ActionType.NOTIFICATION: "notification_action_input",
    ActionType.GENERIC_WEBHOOK: "generic_webhook_action_input",
    ActionType.NO_OP: "no_op_action_input",
}


def prepare_action_config(obj: Any) -> TriggeredActionConfig:
    """Return a `TriggeredActionConfig` as required in the input schema of CreateFilterTriggerInput."""
    action_type = get_action_type(type(obj))
    action_config_key = _ACTION_CONFIG_KEYS[action_type]
    return TriggeredActionConfig(**{action_config_key: obj})


def prepare_create_trigger_input(
    obj: PreparedAutomation | NewAutomation,
    **updates: Any,
) -> CreateFilterTriggerInput:
    from .automations import PreparedAutomation

    # Apply any updates to the properties of the automation
    prepared = PreparedAutomation.model_validate({**obj.model_dump(), **updates})

    # Prepare the input as required for the GraphQL request
    return CreateFilterTriggerInput(
        name=prepared.name,
        description=prepared.description,
        enabled=prepared.enabled,
        client_mutation_id=prepared.client_mutation_id,
        scope_type=get_scope_type(prepared.scope),
        scope_id=prepared.scope.id,
        triggering_event_type=get_event_type(type(prepared.event)),
        event_filter=prepared.event.filter,
        triggered_action_type=get_action_type(type(prepared.action)),
        triggered_action_config=prepare_action_config(prepared.action),
    )
