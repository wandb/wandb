# ruff: noqa: UP007  # Avoid using `X | Y` for union fields, as this can cause issues with pydantic < 2.6

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, TypedDict

from wandb._pydantic import to_json
from wandb.automations.events import InputEvent
from wandb.automations.scopes import InputScope

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
    InputAction,
    SavedAction,
)

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from .automations import Automation, NewAutomation


class HasId(Protocol):
    id: str


def extract_id(obj: HasId | str) -> str:
    return obj.id if hasattr(obj, "id") else obj


# NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
# so we deliberately don't currently expose it in the API for *creating* automations.
_ACTION_CONFIG_KEYS: dict[ActionType, str] = {
    ActionType.NOTIFICATION: "notification_action_input",
    ActionType.GENERIC_WEBHOOK: "generic_webhook_action_input",
    ActionType.NO_OP: "no_op_action_input",
}


class InputActionConfig(TriggeredActionConfig):
    """A `TriggeredActionConfig` that prepares the action config for saving an automation."""

    notification_action_input: Optional[DoNotification] = None
    generic_webhook_action_input: Optional[DoWebhook] = None
    no_op_action_input: Optional[DoNothing] = None


def prepare_action_input(obj: InputAction | SavedAction) -> InputActionConfig:
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

    scope: InputScope
    event: InputEvent
    action: InputAction


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
        event_filter=to_json(prepared.event.filter),
        triggered_action_type=prepared.action.action_type,
        triggered_action_config=prepare_action_input(prepared.action).model_dump(),
    )


def prepare_update_input(
    obj: Automation, **updates: Unpack[AutomationParams]
) -> UpdateFilterTriggerInput:
    """Prepares the payload to update an automation in a GraphQL request."""
    from .events import SavedEventFilter

    updated = obj.model_copy(update=updates)

    return UpdateFilterTriggerInput(
        id=updated.id,
        name=updated.name,
        description=updated.description,
        enabled=updated.enabled,
        scope_type=updated.scope.scope_type,
        scope_id=updated.scope.id,
        triggering_event_type=updated.event.event_type,
        event_filter=to_json(
            updated.event.filter.filter
            if isinstance(updated.event.filter, SavedEventFilter)
            else updated.event.filter
        ),
        triggered_action_type=updated.action.action_type,
        triggered_action_config=prepare_action_input(updated.action).model_dump(),
    )
