"""Actions that are triggered by W&B Automations."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BeforeValidator, Field
from typing_extensions import Annotated, Self, get_args

from wandb._pydantic import GQLBase, GQLId, Typename
from wandb._strutils import nameof

from ._generated import (
    AlertSeverity,
    GenericWebhookActionFields,
    GenericWebhookActionInput,
    NoOpActionFields,
    NoOpTriggeredActionInput,
    NotificationActionFields,
    NotificationActionInput,
    QueueJobActionFields,
)
from ._validators import (
    LenientStrEnum,
    SerializedToJson,
    default_if_none,
    to_input_action,
    to_saved_action,
    upper_if_str,
)
from .integrations import SlackIntegration, WebhookIntegration


# NOTE: Name shortened for readability and defined publicly for easier access
class ActionType(LenientStrEnum):
    """The type of action triggered by an automation."""

    QUEUE_JOB = "QUEUE_JOB"  # NOTE: Deprecated for creation
    NOTIFICATION = "NOTIFICATION"
    GENERIC_WEBHOOK = "GENERIC_WEBHOOK"
    NO_OP = "NO_OP"


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations


# NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
# so while we allow parsing it from previously saved Automations, we deliberately
# don't currently expose it in the API for creating automations.
class SavedLaunchJobAction(QueueJobActionFields):
    action_type: Literal[ActionType.QUEUE_JOB] = ActionType.QUEUE_JOB


# FIXME: Find a better place to put these OR a better way to handle the
#   conversion from `InputAction` -> `SavedAction`.
#
# Necessary placeholder class defs for converting:
# - `SendNotification -> SavedNotificationAction`
# - `SendWebhook -> SavedWebhookAction`
#
# The "input" types (`Send{Notification,Webhook}`) will only have an `integration_id`,
# and we don't want/need to fetch the other `{Slack,Webhook}Integration` fields if
# we can avoid it.
class _SavedActionSlackIntegration(GQLBase, extra="allow"):
    typename__: Typename[Literal["SlackIntegration"]] = "SlackIntegration"
    id: GQLId


class _SavedActionWebhookIntegration(GQLBase, extra="allow"):
    typename__: Typename[Literal["GenericWebhookIntegration"]] = (
        "GenericWebhookIntegration"
    )
    id: GQLId


class SavedNotificationAction(NotificationActionFields):
    action_type: Literal[ActionType.NOTIFICATION] = ActionType.NOTIFICATION
    integration: _SavedActionSlackIntegration


class SavedWebhookAction(GenericWebhookActionFields):
    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK
    integration: _SavedActionWebhookIntegration

    # We override the type of the `requestPayload` field since the original GraphQL
    # schema (and generated class) effectively defines it as a string, when we know
    # and need to anticipate the expected structure of the JSON-serialized data.
    request_payload: Annotated[
        Optional[SerializedToJson[dict[str, Any]]],
        Field(alias="requestPayload"),
    ] = None  # type: ignore[assignment]


class SavedNoOpAction(NoOpActionFields, frozen=True):
    action_type: Literal[ActionType.NO_OP] = ActionType.NO_OP

    no_op: Annotated[bool, BeforeValidator(default_if_none)] = True
    """Placeholder field, only needed to conform to schema requirements.

    There should never be a need to set this field explicitly, as its value is ignored.
    """


# for type annotations
SavedAction = Annotated[
    Union[
        SavedLaunchJobAction,
        SavedNotificationAction,
        SavedWebhookAction,
        SavedNoOpAction,
    ],
    BeforeValidator(to_saved_action),
    Field(discriminator="typename__"),
]
# for runtime type checks
SavedActionTypes: tuple[type, ...] = get_args(SavedAction.__origin__)  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------
# Input types: for creating or updating automations
class _BaseActionInput(GQLBase):
    action_type: Annotated[ActionType, Field(frozen=True)]
    """The kind of action to be triggered."""


class SendNotification(_BaseActionInput, NotificationActionInput):
    """Defines an automation action that sends a (Slack) notification."""

    action_type: Literal[ActionType.NOTIFICATION] = ActionType.NOTIFICATION

    integration_id: GQLId
    """The ID of the Slack integration that will be used to send the notification."""

    # Note: Validation aliases are meant to provide continuity with prior `wandb.alert()` API.
    title: str = ""
    """The title of the sent notification."""

    message: Annotated[str, Field(validation_alias="text")] = ""
    """The message body of the sent notification."""

    severity: Annotated[
        AlertSeverity,
        BeforeValidator(upper_if_str),  # Be helpful by ensuring uppercase strings
        Field(validation_alias="level"),
    ] = AlertSeverity.INFO
    """The severity (`INFO`, `WARN`, `ERROR`) of the sent notification."""

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
        return cls(
            integration_id=integration.id,
            title=title,
            message=text,
            severity=level,
        )


class SendWebhook(_BaseActionInput, GenericWebhookActionInput):
    """Defines an automation action that sends a webhook request."""

    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK

    integration_id: GQLId
    """The ID of the webhook integration that will be used to send the request."""

    # overrides the generated field type to parse/serialize JSON strings
    request_payload: Optional[SerializedToJson[dict[str, Any]]] = Field(  # type: ignore[assignment]
        default=None, alias="requestPayload"
    )
    """The payload, possibly with template variables, to send in the webhook request."""

    @classmethod
    def from_integration(
        cls,
        integration: WebhookIntegration,
        *,
        payload: Optional[SerializedToJson[dict[str, Any]]] = None,
    ) -> Self:
        """Define a webhook action that sends to the given (webhook) integration."""
        return cls(integration_id=integration.id, request_payload=payload)


class DoNothing(_BaseActionInput, NoOpTriggeredActionInput, frozen=True):
    """Defines an automation action that intentionally does nothing."""

    action_type: Literal[ActionType.NO_OP] = ActionType.NO_OP

    no_op: Annotated[bool, BeforeValidator(default_if_none)] = True
    """Placeholder field which exists only to satisfy backend schema requirements.

    There should never be a need to set this field explicitly, as its value is ignored.
    """


# for type annotations
InputAction = Annotated[
    Union[
        SendNotification,
        SendWebhook,
        DoNothing,
    ],
    BeforeValidator(to_input_action),
    Field(discriminator="action_type"),
]
# for runtime type checks
InputActionTypes: tuple[type, ...] = get_args(InputAction.__origin__)  # type: ignore[attr-defined]

__all__ = [
    "ActionType",
    *(nameof(cls) for cls in InputActionTypes),
]
