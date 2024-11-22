"""Actions that are triggered by W&B Automations."""

from __future__ import annotations

import sys
from typing import Literal, Union

from pydantic import AliasChoices, BeforeValidator, Field, JsonValue

from ._generated import (
    AlertSeverity,
    GenericWebhookActionFields,
    GenericWebhookActionInput,
    GQLBase,
    NoOpActionFields,
    NoOpTriggeredActionInput,
    NotificationActionFields,
    NotificationActionInput,
    QueueJobActionFields,
    SerializedToJson,
    TriggeredActionType,
    Typename,
)
from ._validators import uppercase_if_str

if sys.version_info >= (3, 12):
    from typing import Annotated
else:
    from typing_extensions import Annotated


# NOTE: Name shortened for readability and defined publicly for easier access
ActionType = TriggeredActionType
"""The type of action triggered by an automation."""


class LaunchJobAction(QueueJobActionFields):
    typename__: Typename[Literal["QueueJobTriggeredAction"]]


class NotificationAction(NotificationActionFields):
    typename__: Typename[Literal["NotificationTriggeredAction"]]


class WebhookAction(GenericWebhookActionFields):
    typename__: Typename[Literal["GenericWebhookTriggeredAction"]]


class NoOpAction(NoOpActionFields):
    typename__: Typename[Literal["NoOpTriggeredAction"]]


# ------------------------------------------------------------------------------


# NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
# so we deliberately don't currently expose it in the API for creating automations.
class _ActionInput(GQLBase):
    action_type: ActionType


# Annotations for NotificationActionInput params
# Validation aliases allow arg names from previous `wandb.alert()` API
_NotificationTitleT = Annotated[
    str,
    Field(default="", alias="title", validation_alias="message"),
]
_NotificationMessageT = Annotated[
    str,
    Field(default="", alias="message", validation_alias="text"),
]
_NotificationSeverityT = Annotated[
    Union[AlertSeverity, str],
    Field(default=AlertSeverity.INFO, alias="severity", validation_alias="level"),
    BeforeValidator(uppercase_if_str),
]


class DoNotification(NotificationActionInput, _ActionInput):
    """Schema for defining a triggered notification action."""

    action_type: Literal[ActionType.NOTIFICATION] = ActionType.NOTIFICATION

    title: _NotificationTitleT = ""
    message: _NotificationMessageT = ""
    severity: _NotificationSeverityT = AlertSeverity.INFO  # type: ignore


# Annotations for GenericWebhookActionInput params
_WebhookPayloadT = Annotated[
    SerializedToJson[JsonValue],
    Field(
        alias=AliasChoices("requestPayload", "request_payload"),
        validation_alias="payload",
    ),
]


class DoWebhook(GenericWebhookActionInput, _ActionInput):
    """Schema for defining a triggered webhook action."""

    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK

    request_payload: _WebhookPayloadT | None = None


class DoNothing(NoOpTriggeredActionInput, _ActionInput):
    """Schema for defining a triggered no-op action."""

    action_type: Literal[ActionType.NO_OP] = ActionType.NO_OP
