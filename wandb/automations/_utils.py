from __future__ import annotations

from collections.abc import Collection
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any, Final, Protocol, TypedDict

from pydantic import Field
from typing_extensions import Self, Unpack

from wandb._pydantic import GQLId, GQLInput, computed_field, model_validator, to_json
from wandb._strutils import nameof

from ._filters import MongoLikeFilter
from ._generated import (
    CreateFilterTriggerInput,
    EntityScopeFields,
    GenericWebhookActionFields,
    NoOpActionFields,
    NotificationActionFields,
    QueueJobActionFields,
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
    SavedEvent,
    _WrappedSavedEventFilter,
)
from .scopes import AutomationScope, ScopeType

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi

INVALID_INPUT_EVENTS: Final[Collection[EventType]] = (EventType.UPDATE_ARTIFACT_ALIAS,)
"""Event types that should NOT be allowed as new values on new or edited automations.

While we forbid new/edited automations from assigning these event types,
they're defined so that we can still parse existing automations that may use them.
"""

INVALID_INPUT_ACTIONS: Final[Collection[ActionType]] = (
    ActionType.QUEUE_JOB,
    ActionType.PUSH_NOTIFICATION,
)
"""Action types that should NOT be allowed as new values on new or edited automations.

While we forbid new/edited automations from assigning these action types,
they're defined so that we can still parse existing automations that may use them.
"""

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


@lru_cache(maxsize=16)
def scope_enabled(service_api: ServiceApi, scope: ScopeType) -> bool:
    """Returns whether the server supports the automation scope."""
    flag_name = f"AUTOMATION_SCOPE_{scope.value}"
    return (scope in UNGATED_SCOPES) or service_api.feature_enabled(flag_name)


@lru_cache(maxsize=16)
def event_enabled(service_api: ServiceApi, event: EventType) -> bool:
    """Returns whether the server supports the automation event."""
    flag_name = f"AUTOMATION_EVENT_{event.value}"
    return (event in UNGATED_EVENTS) or service_api.feature_enabled(flag_name)


@lru_cache(maxsize=16)
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


@lru_cache(maxsize=16)
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


class HasId(Protocol):
    id: str


def extract_id(obj: HasId | str) -> str:
    return obj if isinstance(obj, str) else obj.id


# ---------------------------------------------------------------------------


class ActionSpecInput(TriggeredActionConfig):
    """Input action spec for saving an automation."""

    # NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
    # so while it's allowed here to update EXISTING mutations, we don't
    # currently expose it through the public API to create NEW automations.
    queue_job_action_input: QueueJobActionInput | None = None

    notification_action_input: SendNotification | None = None
    generic_webhook_action_input: SendWebhook | None = None
    no_op_action_input: DoNothing | None = None

    @classmethod
    def from_action(cls, obj: SavedAction | InputAction) -> Self:
        """Nests the action input under the correct key for `TriggeredActionConfig`.

        This is necessary to conform to the schemas for:
        - `CreateFilterTriggerInput`
        - `UpdateFilterTriggerInput`
        """
        match (parsed := parse_input_action(obj)).action_type:
            case ActionType.NOTIFICATION:
                return cls(notification_action_input=parsed)
            case ActionType.GENERIC_WEBHOOK:
                return cls(generic_webhook_action_input=parsed)
            case ActionType.NO_OP:
                return cls(no_op_action_input=parsed)
            case ActionType.QUEUE_JOB:
                return cls(queue_job_action_input=parsed)
            case _:
                return cls.model_validate(parsed)


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
        # model_dump() serializes inner JSON fields like `requestPayload` correctly.
        return ActionSpecInput.from_action(self.action).model_dump()

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


class ValidatedUpdateInput(GQLInput, extra="ignore", frozen=True):
    """Validated automation parameters, prepared for updating an existing automation.

    Accepts both InputEvent/InputAction (user-supplied for the update) and
    SavedEvent/SavedAction (carried over from the existing saved automation).
    This avoids the coercion bug where routing through Automation(event: SavedEvent)
    silently drops InputEvent filters.

    Uses extra="ignore" (rather than "forbid") because dict(Automation) includes
    fields like typename__, created_at, updated_at that are not relevant for the
    update payload.
    """

    id: GQLId

    name: str | None = None
    description: str | None = None
    enabled: bool | None = None

    event: Annotated[InputEvent | SavedEvent, Field(exclude=True)]
    action: Annotated[InputAction | SavedAction, Field(exclude=True)]
    scope: Annotated[AutomationScope, Field(exclude=True)]

    # --------------------------------------------------------------------------
    # Derived fields to match the input schemas
    @computed_field
    def scope_type(self) -> ScopeType:
        return self.scope.scope_type

    @computed_field
    def scope_id(self) -> GQLId:
        return self.scope.id

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
        # model_dump() serializes inner JSON fields like `requestPayload` correctly.
        return ActionSpecInput.from_action(self.action).model_dump()

    # --------------------------------------------------------------------------
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
    obj_dict = (obj.model_dump() | kwargs) if obj else kwargs
    vobj = ValidatedCreateInput(**obj_dict)
    return CreateFilterTriggerInput.model_validate(vobj)


def prepare_to_update(
    obj: Automation | None = None,
    /,
    **kwargs: Unpack[WriteAutomationsKwargs],
) -> UpdateFilterTriggerInput:
    """Prepares the payload to update an automation in a GraphQL request."""
    # Validate all input variables, and prepare as expected by the GraphQL request.
    # - if an object is provided, override its fields with any keyword args
    # - otherwise, instantiate from the keyword args
    obj_dict = dict(obj or {}) | kwargs
    vobj = ValidatedUpdateInput(**obj_dict)
    return UpdateFilterTriggerInput.model_validate(vobj)
