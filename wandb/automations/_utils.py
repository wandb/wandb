# ruff: noqa: UP007  # Avoid using `X | Y` for union fields, as this can cause issues with pydantic < 2.6

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Optional, Protocol, TypedDict

from wandb._pydantic import to_json

from ._generated import (
    CreateFilterTriggerInput,
    QueueJobActionInput,
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
from .events import EventType, InputEvent, SavedEventFilter
from .scopes import InputScope

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from .automations import Automation, NewAutomation

ALWAYS_SUPPORTED_EVENTS: Final[frozenset[EventType]] = frozenset(
    {
        EventType.CREATE_ARTIFACT,
        EventType.LINK_MODEL,
        EventType.ADD_ARTIFACT_ALIAS,
    }
)
"""Event types that we can safely assume all contemporary server versions support."""

ALWAYS_SUPPORTED_ACTIONS: Final[frozenset[ActionType]] = frozenset(
    {
        ActionType.NOTIFICATION,
        ActionType.GENERIC_WEBHOOK,
    }
)
"""Action types that we can safely assume all contemporary server versions support."""


class HasId(Protocol):
    id: str


def extract_id(obj: HasId | str) -> str:
    return obj.id if hasattr(obj, "id") else obj


ACTION_CONFIG_KEYS: dict[ActionType, str] = {
    ActionType.NOTIFICATION: "notification_action_input",
    ActionType.GENERIC_WEBHOOK: "generic_webhook_action_input",
    ActionType.NO_OP: "no_op_action_input",
    ActionType.QUEUE_JOB: "queue_job_action_input",
}


class InputActionConfig(TriggeredActionConfig):
    """A `TriggeredActionConfig` that prepares the action config for saving an automation."""

    # NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
    # so while it's allowed here to update EXISTING mutations, we don't
    # currently expose it through the public API to create NEW automations.
    queue_job_action_input: Optional[QueueJobActionInput] = None

    notification_action_input: Optional[DoNotification] = None
    generic_webhook_action_input: Optional[DoWebhook] = None
    no_op_action_input: Optional[DoNothing] = None


def prepare_action_input(obj: InputAction | SavedAction) -> dict[str, Any]:
    """Automatically nest the action under the appropriate key.

    This is necessary to conform to the schemas for:
    - CreateFilterTriggerInput
    - UpdateFilterTriggerInput
    """
    # Delegate to inner validators to convert SavedAction -> InputAction types, if needed.
    validated = InputActionConfig(**{ACTION_CONFIG_KEYS[obj.action_type]: obj})
    # `.model_dump()` is necessary to serialize inner JSONString fields (e.g. webhook payloads)
    # correctly, in order to comply with input schemas
    return validated.model_dump()


class AutomationParams(TypedDict, total=False):
    """Keyword arguments that can be passed to create or update an automation."""

    name: str
    description: str
    enabled: bool

    scope: InputScope
    event: InputEvent
    action: InputAction


def prepare_create_input(
    obj: NewAutomation | None = None,
    /,
    **updates: Unpack[AutomationParams],
) -> CreateFilterTriggerInput:
    """Prepares the payload to create an automation in a GraphQL request."""
    from .automations import PreparedAutomation

    # Validate, applying any keyword arg values as overrides.
    # Or instantiate from the keyword args if no instance was given.
    v_obj = PreparedAutomation(**{**dict(obj or {}), **updates})

    # Prepare the input as required for the GraphQL request
    return CreateFilterTriggerInput(
        name=v_obj.name,
        description=v_obj.description,
        enabled=v_obj.enabled,
        scope_type=v_obj.scope.scope_type,
        scope_id=v_obj.scope.id,
        triggering_event_type=v_obj.event.event_type,
        event_filter=to_json(v_obj.event.filter),
        triggered_action_type=v_obj.action.action_type,
        triggered_action_config=prepare_action_input(v_obj.action),
    )


def prepare_update_input(
    obj: Automation | None = None,
    /,
    **updates: Unpack[AutomationParams],
) -> UpdateFilterTriggerInput:
    """Prepares the payload to update an automation in a GraphQL request."""
    from .automations import Automation

    # Validate, applying any keyword arg values as overrides.
    # Or instantiate from the keyword args if no instance was given.
    v_obj = Automation(**{**dict(obj or {}), **updates})

    return UpdateFilterTriggerInput(
        id=v_obj.id,
        name=v_obj.name,
        description=v_obj.description,
        enabled=v_obj.enabled,
        scope_type=v_obj.scope.scope_type,
        scope_id=v_obj.scope.id,
        triggering_event_type=v_obj.event.event_type,
        event_filter=to_json(
            # Input event filters are nested one level deeper than saved event filters
            v_obj.event.filter.filter
            if isinstance(v_obj.event.filter, SavedEventFilter)
            else v_obj.event.filter
        ),
        triggered_action_type=v_obj.action.action_type,
        triggered_action_config=prepare_action_input(v_obj.action),
    )
