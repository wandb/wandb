from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from ._generated import (
    CreateFilterTriggerInput,
    TriggeredActionConfig,
    UpdateFilterTriggerInput,
)
from .actions import (
    ActionType,
    DoNothing,
    DoNotification,
    DoWebhook,
    _InputAction,
    _SavedAction,
)

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from .automations import (
        Automation,
        NewAutomation,
        _ActionInputT,
        _EventInputT,
        _ScopeInputT,
    )


# NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
# so we deliberately don't currently expose it in the API for *creating* automations.
_ACTION_CONFIG_KEYS: dict[ActionType, str] = {
    ActionType.NOTIFICATION: "notification_action_input",
    ActionType.GENERIC_WEBHOOK: "generic_webhook_action_input",
    ActionType.NO_OP: "no_op_action_input",
}


class InputActionConfig(TriggeredActionConfig):
    """A `TriggeredActionConfig` that prepares the action config for saving an automation."""

    notification_action_input: DoNotification | None = None
    generic_webhook_action_input: DoWebhook | None = None
    no_op_action_input: DoNothing | None = None


def prepare_action_input(obj: _InputAction | _SavedAction) -> InputActionConfig:
    """Return a `TriggeredActionConfig` as required in the input schema of CreateFilterTriggerInput."""
    key = _ACTION_CONFIG_KEYS[obj.action_type]
    # Delegate the validators for each ActionInput type to handle custom logic
    # for converting from saved action types to an input action type.
    return InputActionConfig.model_validate({key: obj})


class AutomationParams(TypedDict, total=False):
    """Keyword arguments that can be passed to create or update an automation."""

    name: str
    description: str
    enabled: bool

    scope: _ScopeInputT
    event: _EventInputT
    action: _ActionInputT


def prepare_create_input(
    obj: NewAutomation, **updates: Unpack[AutomationParams]
) -> CreateFilterTriggerInput:
    """Prepares the payload to create an automation in a GraphQL request."""
    from .automations import PreparedAutomation

    # Apply any updates to the properties of the automation
    updated = obj.model_copy(update=updates)
    prepared = PreparedAutomation.model_validate(updated)

    # Prepare the input as required for the GraphQL request
    return CreateFilterTriggerInput(
        name=prepared.name,
        description=prepared.description,
        enabled=prepared.enabled,
        scope_type=prepared.scope.scope_type,
        scope_id=prepared.scope.id,
        triggering_event_type=prepared.event.event_type,
        event_filter=prepared.event.filter,
        triggered_action_type=prepared.action.action_type,
        triggered_action_config=prepare_action_input(prepared.action),
    )


def prepare_update_input(
    obj: Automation, **updates: Unpack[AutomationParams]
) -> UpdateFilterTriggerInput:
    """Prepares the payload to update an automation in a GraphQL request."""
    from .events import _WrappedEventFilter

    updated = obj.model_copy(update=updates)

    action_type = updated.action.action_type
    action_config = prepare_action_input(updated.action)
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
