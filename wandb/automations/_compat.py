from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Annotated, Final

from pydantic import Field

from wandb._strutils import nameof

from ._generated import (
    AriaActionFields,
    EntityScopeFields,
    GenericWebhookActionFields,
    NoOpActionFields,
    NotificationActionFields,
    QueueJobActionFields,
)
from ._generated.fragments import (
    ProjectTriggersFields,
    TriggerFields,
    TriggerFieldsActionPushNotificationTriggeredAction,
)
from .actions import ActionType, SavedUnknownAction
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
        ActionType.ARIA,  # No GraphQL @serverFeature; org-gated on the server
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


class _LenientTriggerFields(TriggerFields):
    """`TriggerFields` that keep listing working when the server adds action types."""

    action: Annotated[
        AriaActionFields
        | GenericWebhookActionFields
        | NoOpActionFields
        | NotificationActionFields
        | TriggerFieldsActionPushNotificationTriggeredAction
        | QueueJobActionFields
        | SavedUnknownAction,
        Field(union_mode="left_to_right"),
    ]


_UNKNOWN_ACTION_SUPPORT_INSTALLED = False


def _install_unknown_action_support() -> None:
    """Parse unknown `triggeredAction` union members instead of failing the whole list.

    Generated `TriggerFields.action` is a closed tagged union. A new GraphQL action
    type (ARIA on older SDKs, or the next type after this release) then fails
    `model_validate` for every automation on that page. Swap in a lenient subclass
    that falls back to `SavedUnknownAction`.
    """
    global _UNKNOWN_ACTION_SUPPORT_INSTALLED
    if _UNKNOWN_ACTION_SUPPORT_INSTALLED:
        return

    from wandb.automations._generated.create_automation import (
        CreateAutomation,
        CreateAutomationResult,
    )
    from wandb.automations._generated.get_automations_legacy import (
        GetAutomationsLegacy,
        GetAutomationsLegacyScope,
        GetAutomationsLegacyScopeProjects,
        GetAutomationsLegacyScopeProjectsEdges,
    )
    from wandb.automations._generated.get_entity_automations import (
        GetEntityAutomations,
        GetEntityAutomationsScope,
        GetEntityAutomationsScopeTriggers,
        GetEntityAutomationsScopeTriggersEdges,
    )
    from wandb.automations._generated.get_entity_automations_legacy import (
        GetEntityAutomationsLegacy,
        GetEntityAutomationsLegacyScope,
        GetEntityAutomationsLegacyScopeProjects,
        GetEntityAutomationsLegacyScopeProjectsEdges,
    )
    from wandb.automations._generated.get_org_automations import (
        GetOrgAutomations,
        GetOrgAutomationsScope,
        GetOrgAutomationsScopeTriggers,
        GetOrgAutomationsScopeTriggersEdges,
    )
    from wandb.automations._generated.update_automation import (
        UpdateAutomation,
        UpdateAutomationResult,
    )

    GetEntityAutomationsScopeTriggersEdges.model_fields[
        "node"
    ].annotation = _LenientTriggerFields
    GetOrgAutomationsScopeTriggersEdges.model_fields[
        "node"
    ].annotation = _LenientTriggerFields
    CreateAutomationResult.model_fields["trigger"].annotation = (
        _LenientTriggerFields | None
    )
    UpdateAutomationResult.model_fields["trigger"].annotation = (
        _LenientTriggerFields | None
    )
    ProjectTriggersFields.model_fields["triggers"].annotation = list[
        _LenientTriggerFields
    ]

    for cls in (
        _LenientTriggerFields,
        ProjectTriggersFields,
        GetEntityAutomationsScopeTriggersEdges,
        GetEntityAutomationsScopeTriggers,
        GetEntityAutomationsScope,
        GetEntityAutomations,
        GetOrgAutomationsScopeTriggersEdges,
        GetOrgAutomationsScopeTriggers,
        GetOrgAutomationsScope,
        GetOrgAutomations,
        GetEntityAutomationsLegacyScopeProjectsEdges,
        GetEntityAutomationsLegacyScopeProjects,
        GetEntityAutomationsLegacyScope,
        GetEntityAutomationsLegacy,
        GetAutomationsLegacyScopeProjectsEdges,
        GetAutomationsLegacyScopeProjects,
        GetAutomationsLegacyScope,
        GetAutomationsLegacy,
        CreateAutomationResult,
        CreateAutomation,
        UpdateAutomationResult,
        UpdateAutomation,
    ):
        cls.model_rebuild(force=True)

    _UNKNOWN_ACTION_SUPPORT_INSTALLED = True


_install_unknown_action_support()
