from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypedDict, TypeVar

from ._generated import (
    CreateFilterTriggerInput,
    GenericWebhookActionFields,
    GenericWebhookActionInput,
    GenericWebhookIntegrationFields,
    NoOpActionFields,
    NoOpTriggeredActionInput,
    NotificationActionFields,
    NotificationActionInput,
    SlackIntegrationFields,
    TriggeredActionConfig,
    UpdateFilterTriggerInput,
)
from .actions import ActionType, DoNothing, DoNotification, DoWebhook
from .scopes import ScopeType, _ScopeInfo

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from .automations import (
        Automation,
        NewAutomation,
        _ActionInputT,
        _EventInputT,
        _ScopeInputT,
    )
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
    if issubclass(cls, (NotificationActionInput, NotificationActionFields)):
        return ActionType.NOTIFICATION
    if issubclass(cls, (GenericWebhookActionInput, GenericWebhookActionFields)):
        return ActionType.GENERIC_WEBHOOK
    if issubclass(cls, (NoOpTriggeredActionInput, NoOpActionFields)):
        return ActionType.NO_OP
    raise ValueError(f"Cannot determine action type of {cls!r} object")


_ACTION_CONFIG_KEYS: dict[ActionType, str] = {
    ActionType.NOTIFICATION: "notification_action_input",
    ActionType.GENERIC_WEBHOOK: "generic_webhook_action_input",
    ActionType.NO_OP: "no_op_action_input",
}


def prepare_action_config(obj: Any, action_type: ActionType) -> TriggeredActionConfig:
    """Return a `TriggeredActionConfig` as required in the input schema of CreateFilterTriggerInput."""
    key = _ACTION_CONFIG_KEYS[action_type]

    config_obj: _ActionInputT
    if isinstance(
        obj,
        (NotificationActionInput, GenericWebhookActionInput, NoOpTriggeredActionInput),
    ):
        return TriggeredActionConfig(**{key: obj})

    if isinstance(obj, NotificationActionFields):
        slack_integration = SlackIntegrationFields.model_validate(obj.integration)
        config_obj = DoNotification(
            integration_id=slack_integration.id,
            title=obj.title,
            message=obj.message,
            severity=obj.severity,
        )
        return TriggeredActionConfig(**{key: config_obj})

    if isinstance(obj, GenericWebhookActionFields):
        webhook_integration = GenericWebhookIntegrationFields.model_validate(
            obj.integration
        )
        config_obj = DoWebhook(
            integration_id=webhook_integration.id,
            request_payload=obj.request_payload,
        )
        return TriggeredActionConfig(**{key: config_obj})

    if isinstance(obj, NoOpActionFields):
        config_obj = DoNothing()
        return TriggeredActionConfig(**{key: config_obj})

    raise ValueError(f"Cannot prepare action config for {type(obj)!r} object")


class AutomationParams(TypedDict, total=False):
    """Keyword arguments that can be passed to create or update an automation."""

    name: str
    description: str
    enabled: bool

    scope: _ScopeInputT
    event: _EventInputT
    action: _ActionInputT

    client_mutation_id: str


def prepare_create_input(
    obj: NewAutomation, **updates: Unpack[AutomationParams]
) -> CreateFilterTriggerInput:
    """Prepares the payload to create an automation in a GraphQL request."""
    from .automations import PreparedAutomation

    # Apply any updates to the properties of the automation
    updated = obj.model_copy(update=updates)
    prepared = PreparedAutomation.model_validate(updated)

    # Prepare the input as required for the GraphQL request
    action_type = prepared.action.action_type
    action_config = prepare_action_config(prepared.action, action_type)
    return CreateFilterTriggerInput(
        name=prepared.name,
        description=prepared.description,
        enabled=prepared.enabled,
        client_mutation_id=prepared.client_mutation_id,
        scope_type=prepared.scope.scope_type,
        scope_id=prepared.scope.id,
        triggering_event_type=prepared.event.event_type,
        event_filter=prepared.event.filter,
        triggered_action_type=action_type,
        triggered_action_config=action_config,
    )


def prepare_update_input(
    obj: Automation, **updates: Unpack[AutomationParams]
) -> UpdateFilterTriggerInput:
    """Prepares the payload to update an automation in a GraphQL request."""
    from .events import _WrappedEventFilter

    updated = obj.model_copy(update=updates)

    action_type = get_action_type(type(updated.action))
    action_config = prepare_action_config(updated.action, action_type)
    return UpdateFilterTriggerInput(
        id=updated.id,
        name=updated.name,
        description=updated.description,
        enabled=updated.enabled,
        scope_type=updated.scope.scope_type,
        scope_id=updated.scope.id,
        triggering_event_type=updated.event.event_type,
        event_filter=(
            updated.event.filter.filter
            if isinstance(updated.event.filter, _WrappedEventFilter)
            else updated.event.filter
        ),
        triggered_action_type=action_type,
        triggered_action_config=action_config,
    )
