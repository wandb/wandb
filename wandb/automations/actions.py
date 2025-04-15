"""Actions that are triggered by W&B Automations."""

# ruff: noqa: UP007  # Avoid using `X | Y` for union fields, as this can cause issues with pydantic < 2.6

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field
from typing_extensions import Self, TypeAlias, get_args

from wandb._pydantic import (
    SerializedToJson,
    field_validator,
    model_validator,
    pydantic_isinstance,
)

from ._generated import (
    AlertSeverity,
    GenericWebhookActionFields,
    GenericWebhookActionInput,
    NoOpActionFields,
    NoOpTriggeredActionInput,
    NotificationActionFields,
    NotificationActionInput,
    QueueJobActionFields,
    TriggeredActionType,
)
from .integrations import SlackIntegration, WebhookIntegration

# Note: Pydantic doesn't like `list['JsonValue']` or `dict[str, 'JsonValue']`,
# which causes a RecursionError.
JsonValue: TypeAlias = Union[
    List[Any],
    Dict[str, Any],
    # NOTE: For now, we're not expecting any doubly-serialized strings, as this makes validation logic easier, but revisit and revise if needed.
    # str,
    bool,
    int,
    float,
    None,
]

# NOTE: Name shortened for readability and defined publicly for easier access
ActionType = TriggeredActionType
"""The type of action triggered by an automation."""


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations


# NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
# so while we allow parsing it from previously saved Automations, we deliberately
# don't currently expose it in the API for creating automations.
class SavedLaunchJobAction(QueueJobActionFields):
    action_type: Literal[ActionType.QUEUE_JOB] = ActionType.QUEUE_JOB


class SavedNotificationAction(NotificationActionFields):
    action_type: Literal[ActionType.NOTIFICATION] = ActionType.NOTIFICATION


class SavedWebhookAction(GenericWebhookActionFields):
    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK

    # We override the type of the `requestPayload` field since the original GraphQL
    # schema (and generated class) effectively defines it as a string, when we know
    # and need to anticipate the expected structure of the JSON-serialized data.
    request_payload: Optional[SerializedToJson[JsonValue]] = Field(  # type: ignore[assignment]
        default=None, alias="requestPayload"
    )


class SavedNoOpAction(NoOpActionFields):
    action_type: Literal[ActionType.NO_OP] = ActionType.NO_OP


# for type annotations
SavedAction = Union[
    SavedLaunchJobAction,
    SavedNotificationAction,
    SavedWebhookAction,
    SavedNoOpAction,
]
# for runtime type checks
SavedActionTypes: tuple[type, ...] = get_args(SavedAction)


# ------------------------------------------------------------------------------
# Input types: for creating or updating automations
class DoNotification(NotificationActionInput):
    """Schema for defining a triggered notification action."""

    action_type: Literal[ActionType.NOTIFICATION] = ActionType.NOTIFICATION

    # Note: Validation aliases match arg names from `wandb.alert()` to allow
    # continuity with previous API.
    title: str = Field(default="", validation_alias="title")
    message: str = Field(default="", validation_alias="text")
    severity: AlertSeverity = Field(
        default=AlertSeverity.INFO, validation_alias="level"
    )

    @field_validator("severity", mode="before")
    @classmethod
    def _validate_severity(cls, v: Any) -> Any:
        # Be helpful by accepting case-insensitive strings
        return v.upper() if isinstance(v, str) else v

    @model_validator(mode="before")
    @classmethod
    def _from_saved(cls, v: Any) -> Any:
        """Convert an action on a saved automation to a new/input action."""
        if pydantic_isinstance(v, SavedNotificationAction):
            return cls(
                integration_id=v.integration.id,
                title=v.title,
                message=v.message,
                severity=v.severity,
            )
        return v

    @classmethod
    def from_integration(
        cls,
        integration: SlackIntegration,
        *,
        title: str = "",
        text: str = "",
        level: AlertSeverity = AlertSeverity.INFO,
    ) -> Self:
        """Define a notification action that sends to the given (Slack) integration."""
        integration = SlackIntegration.model_validate(integration)
        return cls(
            integration_id=integration.id,
            title=title,
            message=text,
            severity=level,
        )


class DoWebhook(GenericWebhookActionInput):
    """Schema for defining a triggered webhook action."""

    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK

    # overrides the generated field type to parse/serialize JSON strings
    request_payload: Optional[SerializedToJson[JsonValue]] = Field(  # type: ignore[assignment]
        default=None, alias="requestPayload"
    )

    @model_validator(mode="before")
    @classmethod
    def _from_saved(cls, v: Any) -> Any:
        """Convert an action on a saved automation to a new/input action."""
        if pydantic_isinstance(v, SavedWebhookAction):
            return cls(
                integration_id=v.integration.id,
                request_payload=v.request_payload,
            )
        return v

    @classmethod
    def from_integration(
        cls,
        integration: WebhookIntegration,
        *,
        request_payload: Optional[SerializedToJson[JsonValue]] = None,
    ) -> Self:
        """Define a webhook action that sends to the given (webhook) integration."""
        integration = WebhookIntegration.model_validate(integration)
        return cls(integration_id=integration.id, request_payload=request_payload)


class DoNothing(NoOpTriggeredActionInput):
    """Schema for defining a triggered no-op action."""

    action_type: Literal[ActionType.NO_OP] = ActionType.NO_OP

    no_op: bool = True  # prevent exclusion on `.model_dump(exclude_none=True)`

    @field_validator("no_op", mode="before")
    @classmethod
    def _ensure_nonnull(cls, v: Any) -> Any:
        # Ensuring the value isn't None complies with validation and
        # prevents the field (and action data) from getting excluded on
        # `.model_dump(exclude_none=True)`
        return True if (v is None) else v


DoNotification.model_rebuild()
DoWebhook.model_rebuild()
DoNothing.model_rebuild()


# for type annotations
InputAction = Union[
    DoNotification,
    DoWebhook,
    DoNothing,
]
# for runtime type checks
InputActionTypes: tuple[type, ...] = get_args(InputAction)
