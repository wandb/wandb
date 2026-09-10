from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Final

from wandb._strutils import nameof
from wandb.proto.wandb_internal_pb2 import ServerFeature

from ._generated import (
    AriaActionFields,
    EntityScopeFields,
    GenericWebhookActionFields,
    NoOpActionFields,
    NotificationActionFields,
    QueueJobActionFields,
)
from .actions import ActionType
from .events import EventType
from .scopes import ScopeType

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi

UNGATED_SCOPES: Final[Collection[ScopeType]] = frozenset(
    {
        ScopeType.ARTIFACT_COLLECTION,
        ScopeType.PROJECT,
    }
)
"""Scope types that should be supported by all current, non-EOL server versions."""

UNGATED_EVENTS: Final[Collection[EventType]] = frozenset(
    {
        EventType.CREATE_ARTIFACT,
        EventType.LINK_ARTIFACT,
        EventType.ADD_ARTIFACT_ALIAS,
        EventType.RUN_METRIC_THRESHOLD,  # Added in 0.67.0
        EventType.RUN_METRIC_CHANGE,  # Added in 0.67.0
        EventType.RUN_STATE,  # Added in 0.69.0
    }
)
"""Event types that should be supported by all current, non-EOL server versions."""

UNGATED_ACTIONS: Final[Collection[ActionType]] = frozenset(
    {
        ActionType.NOTIFICATION,
        ActionType.GENERIC_WEBHOOK,
        ActionType.NO_OP,  # Added in 0.67.0
    }
)
"""Action types that should be supported by all current, non-EOL server versions."""

# Explicit ServerFeature names so they stay grep-able. Types with no matching
# proto flag are omitted; lookups treat a missing entry as disabled.
SCOPE_FEATURES: Final[dict[ScopeType, ServerFeature]] = {
    ScopeType.ENTITY: ServerFeature.AUTOMATION_SCOPE_ENTITY,
}

EVENT_FEATURES: Final[dict[EventType, ServerFeature]] = {
    EventType.RUN_METRIC_THRESHOLD: ServerFeature.AUTOMATION_EVENT_RUN_METRIC,
    EventType.RUN_METRIC_CHANGE: ServerFeature.AUTOMATION_EVENT_RUN_METRIC_CHANGE,
    EventType.RUN_METRIC_ZSCORE: ServerFeature.AUTOMATION_EVENT_RUN_METRIC_ZSCORE,
    EventType.RUN_STATE: ServerFeature.AUTOMATION_EVENT_RUN_STATE,
    EventType.ADD_ARTIFACT_TAG: ServerFeature.AUTOMATION_EVENT_ADD_ARTIFACT_TAG,
    EventType.ADD_COLLECTION_TAG: ServerFeature.AUTOMATION_EVENT_ADD_COLLECTION_TAG,
    EventType.REMOVE_ARTIFACT_TAG: ServerFeature.AUTOMATION_EVENT_REMOVE_ARTIFACT_TAG,
    EventType.REMOVE_COLLECTION_TAG: ServerFeature.AUTOMATION_EVENT_REMOVE_COLLECTION_TAG,
    EventType.UNLINK_ARTIFACT: ServerFeature.AUTOMATION_EVENT_UNLINK_ARTIFACT,
}

ACTION_FEATURES: Final[dict[ActionType, ServerFeature]] = {
    ActionType.NO_OP: ServerFeature.AUTOMATION_ACTION_NO_OP,
    ActionType.PUSH_NOTIFICATION: ServerFeature.AUTOMATION_ACTION_PUSH_NOTIFICATION,
    ActionType.ARIA: ServerFeature.AUTOMATION_ACTION_ARIA,
}


def scope_enabled(service_api: ServiceApi, scope: ScopeType) -> bool:
    """Returns whether the server supports the automation scope."""
    if scope in UNGATED_SCOPES:
        return True
    feature = SCOPE_FEATURES.get(scope)
    return feature is not None and service_api.feature_enabled(feature)


def event_enabled(service_api: ServiceApi, event: EventType) -> bool:
    """Returns whether the server supports the automation event."""
    if event in UNGATED_EVENTS:
        return True
    feature = EVENT_FEATURES.get(event)
    return feature is not None and service_api.feature_enabled(feature)


def action_enabled(service_api: ServiceApi, action: ActionType) -> bool:
    """Returns whether the server supports the automation action."""
    if action in UNGATED_ACTIONS:
        return True
    feature = ACTION_FEATURES.get(action)
    return feature is not None and service_api.feature_enabled(feature)


def automation_enabled(
    service_api: ServiceApi,
    *,
    scope: ScopeType,
    event: EventType,
    action: ActionType,
) -> bool:
    """Returns whether the server supports the automation's scope, event, and action."""
    return (
        scope_enabled(service_api, scope)
        and event_enabled(service_api, event)
        and action_enabled(service_api, action)
    )


SCOPE_FRAGMENT_NAMES: Final[dict[ScopeType, str]] = {
    ScopeType.ENTITY: nameof(EntityScopeFields),
}

ACTION_FRAGMENT_NAMES: Final[dict[ActionType, str]] = {
    ActionType.NO_OP: nameof(NoOpActionFields),
    ActionType.QUEUE_JOB: nameof(QueueJobActionFields),
    ActionType.NOTIFICATION: nameof(NotificationActionFields),
    ActionType.GENERIC_WEBHOOK: nameof(GenericWebhookActionFields),
    ActionType.ARIA: nameof(AriaActionFields),
}


def omit_automation_fragments(service_api: ServiceApi) -> set[str]:
    """Returns the names of unsupported automation-related fragments.

    Older servers won't recognize newer GraphQL types, so a valid request may
    unnecessarily error out because it won't recognize fragments defined on those types.

    So e.g. if a server does not support `NO_OP` action types, then the following must be
    removed from the body of the GraphQL request:

        - Fragment definition:
            ```
            fragment NoOpActionFields on NoOpTriggeredAction {
                noOp
            }
            ```

        - Fragment spread in selection set:
            ```
            {
                ...NoOpActionFields
                # ... other fields ...
            }
            ```
    """
    omit_scope_fragments = set(
        name
        for scope in ScopeType
        if (not scope_enabled(service_api, scope))
        and (name := SCOPE_FRAGMENT_NAMES.get(scope))
    )
    omit_action_fragments = set(
        name
        for action in ActionType
        if (not action_enabled(service_api, action))
        and (name := ACTION_FRAGMENT_NAMES.get(action))
    )
    return omit_scope_fragments | omit_action_fragments
