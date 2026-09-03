from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Final

from wandb._strutils import nameof

from ._generated import (
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


def scope_enabled(service_api: ServiceApi, scope: ScopeType) -> bool:
    """Returns whether the server supports the automation scope."""
    flag_name = f"AUTOMATION_SCOPE_{scope.value}"
    return (scope in UNGATED_SCOPES) or service_api.feature_enabled(flag_name)


def event_enabled(service_api: ServiceApi, event: EventType) -> bool:
    """Returns whether the server supports the automation event."""
    flag_name = f"AUTOMATION_EVENT_{event.value}"
    return (event in UNGATED_EVENTS) or service_api.feature_enabled(flag_name)


def action_enabled(service_api: ServiceApi, action: ActionType) -> bool:
    """Returns whether the server supports the automation action."""
    flag_name = f"AUTOMATION_ACTION_{action.value}"
    return (action in UNGATED_ACTIONS) or service_api.feature_enabled(flag_name)


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
