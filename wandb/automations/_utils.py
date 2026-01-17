from __future__ import annotations

from collections.abc import Collection
from typing import Annotated, Any, Final, Protocol, TypedDict

from pydantic import Field, computed_field, model_validator
from typing_extensions import Self, Unpack

from wandb._pydantic import GQLId, GQLInput, to_json

from ._filters import MongoLikeFilter
from ._generated import (
    CreateFilterTriggerInput,
    QueueJobActionInput,
    TriggeredActionConfig,
    UpdateFilterTriggerInput,
)
from ._validators import parse_input_action
from .actions import (
    ActionType,
    DoNothing,
    InputAction,
    SavedAction,
    SendNotification,
    SendWebhook,
)
from .automations import Automation, NewAutomation
from .events import (
    EventType,
    InputEvent,
    RunMetricFilter,
    RunStateFilter,
    _WrappedSavedEventFilter,
)
from .scopes import AutomationScope, ScopeType

INVALID_INPUT_EVENTS: Final[Collection[EventType]] = (EventType.UPDATE_ARTIFACT_ALIAS,)
"""Event types that should NOT be allowed as new values on new or edited automations.

While we forbid new/edited automations from assigning these event types,
they're defined so that we can still parse existing automations that may use them.
"""

INVALID_INPUT_ACTIONS: Final[Collection[ActionType]] = (ActionType.QUEUE_JOB,)
"""Action types that should NOT be allowed as new values on new or edited automations.

While we forbid new/edited automations from assigning these action types,
they're defined so that we can still parse existing automations that may use them.
"""

ALWAYS_SUPPORTED_EVENTS: Final[Collection[EventType]] = frozenset(
    {
        EventType.CREATE_ARTIFACT,
        EventType.LINK_ARTIFACT,
        EventType.ADD_ARTIFACT_ALIAS,
    }
)
"""Event types that should be supported by all current, non-EOL server versions."""

ALWAYS_SUPPORTED_ACTIONS: Final[Collection[ActionType]] = frozenset(
    {
        ActionType.NOTIFICATION,
        ActionType.GENERIC_WEBHOOK,
    }
)
"""Action types that should be supported by all current, non-EOL server versions."""


class HasId(Protocol):
    id: str


def extract_id(obj: HasId | str) -> str:
    return obj.id if hasattr(obj, "id") else obj


# ---------------------------------------------------------------------------
ACTION_CONFIG_KEYS: dict[ActionType, str] = {
    ActionType.NOTIFICATION: "notification_action_input",
    ActionType.GENERIC_WEBHOOK: "generic_webhook_action_input",
    ActionType.NO_OP: "no_op_action_input",
    ActionType.QUEUE_JOB: "queue_job_action_input",
}


class InputActionConfig(TriggeredActionConfig):
    """Prepares action configuration data for saving an automation."""

    # NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
    # so while it's allowed here to update EXISTING mutations, we don't
    # currently expose it through the public API to create NEW automations.
    queue_job_action_input: QueueJobActionInput | None = None

    notification_action_input: SendNotification | None = None
    generic_webhook_action_input: SendWebhook | None = None
    no_op_action_input: DoNothing | None = None


def prepare_action_config_input(obj: SavedAction | InputAction) -> dict[str, Any]:
    """Nests the action input under the correct key for `TriggeredActionConfig`.

    This is necessary to conform to the schemas for:
    - `CreateFilterTriggerInput`
    - `UpdateFilterTriggerInput`
    """
    # Delegate to inner validators to convert SavedAction -> InputAction types, if needed.
    obj = parse_input_action(obj)
    return InputActionConfig(**{ACTION_CONFIG_KEYS[obj.action_type]: obj}).model_dump()


def prepare_event_filter_input(
    obj: _WrappedSavedEventFilter | MongoLikeFilter | RunMetricFilter | RunStateFilter,
) -> str:
    """Unnests (if needed) and serializes an `EventFilter` input to JSON.

    This is necessary to conform to the schemas for:
    - `CreateFilterTriggerInput`
    - `UpdateFilterTriggerInput`
    """
    # Input event filters are nested one level deeper than saved event filters.
    # Note that this is NOT the case for run/run metric filters.
    #
    # Yes, this is confusing.  It's also necessary to conform to under-the-hood
    # schemas and logic in the backend.
    if isinstance(obj, _WrappedSavedEventFilter):
        return to_json(obj.filter)
    return to_json(obj)


class WriteAutomationsKwargs(TypedDict, total=False):
    """Keyword arguments that can be passed to create or update an automation."""

    name: str
    description: str
    enabled: bool
    scope: AutomationScope
    event: InputEvent
    action: InputAction


class ValidatedCreateInput(GQLInput, extra="forbid", frozen=True):
    """Validated automation parameters, prepared for creating a new automation.

    Note: Users should never need to instantiate this class directly.
    """

    name: str
    description: str | None = None
    enabled: bool = True

    # ------------------------------------------------------------------------------
    # Set on instantiation, but used to derive other fields and deliberately
    # EXCLUDED from the final GraphQL request vars
    event: Annotated[InputEvent, Field(exclude=True)]
    action: Annotated[InputAction, Field(exclude=True)]

    # ------------------------------------------------------------------------------
    # Derived fields to match the input schemas
    @computed_field
    def scope_type(self) -> ScopeType:
        return self.event.scope.scope_type

    @computed_field
    def scope_id(self) -> GQLId:
        return self.event.scope.id

    @computed_field
    def triggering_event_type(self) -> EventType:
        return self.event.event_type

    @computed_field
    def event_filter(self) -> str:
        return prepare_event_filter_input(self.event.filter)

    @computed_field
    def triggered_action_type(self) -> ActionType:
        return self.action.action_type

    @computed_field
    def triggered_action_config(self) -> dict[str, Any]:
        return prepare_action_config_input(self.action)

    # ------------------------------------------------------------------------------
    # Custom validation
    @model_validator(mode="after")
    def _forbid_legacy_event_types(self) -> Self:
        if (type_ := self.event.event_type) in INVALID_INPUT_EVENTS:
            raise ValueError(f"{type_!r} events cannot be assigned to automations.")
        return self

    @model_validator(mode="after")
    def _forbid_legacy_action_types(self) -> Self:
        if (type_ := self.action.action_type) in INVALID_INPUT_ACTIONS:
            raise ValueError(f"{type_!r} actions cannot be assigned to automations.")
        return self


def prepare_to_create(
    obj: NewAutomation | None = None,
    /,
    **kwargs: Unpack[WriteAutomationsKwargs],
) -> CreateFilterTriggerInput:
    """Prepares the payload to create an automation in a GraphQL request."""
    # Validate all input variables, and prepare as expected by the GraphQL request.
    # - if an object is provided, override its fields with any keyword args
    # - otherwise, instantiate from the keyword args
    obj_dict = {**obj.model_dump(), **kwargs} if obj else kwargs
    vobj = ValidatedCreateInput(**obj_dict)
    return CreateFilterTriggerInput.model_validate(vobj)


def prepare_to_update(
    obj: Automation | None = None,
    /,
    **kwargs: Unpack[WriteAutomationsKwargs],
) -> UpdateFilterTriggerInput:
    """Prepares the payload to update an automation in a GraphQL request."""
    # Validate all values:
    # - if an object is provided, override its fields with any keyword args
    # - otherwise, instantiate from the keyword args
    vobj = Automation(**{**dict(obj or {}), **kwargs})
    return UpdateFilterTriggerInput(
        id=vobj.id,
        name=vobj.name,
        description=vobj.description,
        enabled=vobj.enabled,
        scope_type=vobj.scope.scope_type,
        scope_id=vobj.scope.id,
        triggering_event_type=vobj.event.event_type,
        event_filter=prepare_event_filter_input(vobj.event.filter),
        triggered_action_type=vobj.action.action_type,
        triggered_action_config=prepare_action_config_input(vobj.action),
    )
