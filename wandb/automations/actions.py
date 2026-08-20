"""Actions that are triggered by W&B Automations."""

from __future__ import annotations

from typing import Annotated, Any, Literal, get_args

from pydantic import BeforeValidator, Field
from typing_extensions import Self, TypeVar

from wandb._pydantic import GQLBase, GQLId, default_if_none
from wandb._strutils import nameof

from ._generated import (
    AlertSeverity,
    AriaActionFields,
    ARIAActionInput,
    GenericWebhookActionFields,
    GenericWebhookActionInput,
    NoOpActionFields,
    NoOpTriggeredActionInput,
    NotificationActionFields,
    NotificationActionInput,
    QueueJobActionFields,
)
from ._validators import (
    JsonEncoded,
    LenientStrEnum,
    parse_input_action,
    parse_saved_action,
    upper_if_str,
)
from .integrations import SlackIntegration, WebhookIntegration

T = TypeVar("T")


# NOTE: Name shortened for readability and defined publicly for easier access
class ActionType(LenientStrEnum):
    """The type of action triggered by an automation."""

    NO_OP = "NO_OP"
    QUEUE_JOB = "QUEUE_JOB"  # NOTE: Deprecated for creation
    GENERIC_WEBHOOK = "GENERIC_WEBHOOK"
    NOTIFICATION = "NOTIFICATION"
    ARIA = "ARIA"
    PUSH_NOTIFICATION = "PUSH_NOTIFICATION"


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
class _SlackIntegrationStub(GQLBase):
    typename__: Annotated[
        Literal["SlackIntegration"],
        Field(alias="__typename", frozen=True, repr=False),
    ] = "SlackIntegration"
    id: GQLId


class _WebhookIntegrationStub(GQLBase):
    typename__: Annotated[
        Literal["GenericWebhookIntegration"],
        Field(alias="__typename", frozen=True, repr=False),
    ] = "GenericWebhookIntegration"
    id: GQLId


class SavedNotificationAction(NotificationActionFields, frozen=False):
    action_type: Literal[ActionType.NOTIFICATION] = ActionType.NOTIFICATION
    # Narrowed from the generated parent's broader union: saved actions
    # always come back tagged with the SlackIntegration stub typename.
    integration: _SlackIntegrationStub  # type: ignore[assignment]

    title: str | None
    message: str | None
    severity: AlertSeverity | None


class SavedWebhookAction(GenericWebhookActionFields, frozen=False):
    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK
    # Narrowed from the generated parent's broader union: saved actions
    # always come back tagged with the GenericWebhookIntegration stub typename.
    integration: _WebhookIntegrationStub  # type: ignore[assignment]

    # We override the type of the `requestPayload` field since the original GraphQL
    # schema (and generated class) effectively defines it as a string, when we know
    # and need to anticipate the expected structure of the JSON-serialized data.
    request_payload: JsonEncoded[dict[str, Any]] | None = None  # type: ignore[assignment]


class SavedNoOpAction(NoOpActionFields, frozen=False):
    action_type: Literal[ActionType.NO_OP] = ActionType.NO_OP

    no_op: Annotated[
        bool,
        BeforeValidator(default_if_none),
        Field(repr=False, frozen=True),
    ] = True
    """Placeholder field, only needed to conform to schema requirements.

    There should never be a need to set this field explicitly, as its value is ignored.
    """


class SavedAriaAction(AriaActionFields, frozen=False):
    action_type: Literal[ActionType.ARIA] = ActionType.ARIA

    prompt: str
    """The prompt ARIA receives when this automation is triggered."""


class SavedUnknownAction(GQLBase, extra="allow", frozen=False):
    """An action type this SDK version does not model.

    Returned when listing automations if the server includes a triggered-action
    GraphQL type that this wandb version has no fragment for. Other automations
    in the same response still parse. Creating or updating this action requires
    a newer wandb version.
    """

    typename__: Annotated[str, Field(alias="__typename")] = "UnknownTriggeredAction"
    """The GraphQL `__typename` of the unrecognized action."""


# for type annotations
SavedAction = Annotated[
    SavedLaunchJobAction
    | SavedNotificationAction
    | SavedWebhookAction
    | SavedNoOpAction
    | SavedAriaAction
    | SavedUnknownAction,
    BeforeValidator(parse_saved_action),
]
# for runtime type checks
SavedActionTypes: tuple[type, ...] = (
    SavedLaunchJobAction,
    SavedNotificationAction,
    SavedWebhookAction,
    SavedNoOpAction,
    SavedAriaAction,
    SavedUnknownAction,
)


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

    # Note: Validation aliases preserve continuity with the prior `wandb.alert()` API.
    title: Annotated[str, BeforeValidator(default_if_none)] = ""
    """The title of the sent notification."""

    message: Annotated[
        str,
        BeforeValidator(default_if_none),
        Field(validation_alias="text"),
    ] = ""
    """The message body of the sent notification."""

    severity: Annotated[
        AlertSeverity,
        BeforeValidator(default_if_none),
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
            integration_id=integration.id, title=title, message=text, severity=level
        )


class SendWebhook(_BaseActionInput, GenericWebhookActionInput):
    """Defines an automation action that sends a webhook request."""

    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK

    integration_id: GQLId
    """The ID of the webhook integration that will be used to send the request."""

    # overrides the generated field type to parse/serialize JSON strings
    request_payload: JsonEncoded[dict[str, Any]] | None = Field(  # type: ignore[assignment]
        default=None, alias="requestPayload"
    )
    """The payload, possibly with template variables, to send in the webhook request."""

    @classmethod
    def from_integration(
        cls,
        integration: WebhookIntegration,
        *,
        payload: JsonEncoded[dict[str, Any]] | None = None,
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


class SendPromptToAria(_BaseActionInput, ARIAActionInput):
    """Defines an automation action that sends a prompt to ARIA."""

    action_type: Literal[ActionType.ARIA] = ActionType.ARIA

    prompt: str
    """The prompt ARIA receives when this automation is triggered."""


# for type annotations
InputAction = Annotated[
    SendNotification | SendWebhook | DoNothing | SendPromptToAria,
    BeforeValidator(parse_input_action),
    Field(discriminator="action_type"),
]
# for runtime type checks
InputActionTypes: tuple[type, ...] = get_args(InputAction.__origin__)  # type: ignore[attr-defined]

__all__ = [
    "ActionType",
    *(nameof(cls) for cls in InputActionTypes),
]
