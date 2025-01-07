"""Actions that are triggered by W&B Automations."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from pydantic import AliasChoices, BeforeValidator, Field, JsonValue, model_validator

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
from ._validators import pydantic_isinstance, uppercase_if_str

if TYPE_CHECKING:
    from wandb.apis.public.integrations import SlackIntegration, WebhookIntegration

if sys.version_info >= (3, 12):
    from typing import Annotated, Self
else:
    from typing_extensions import Annotated, Self


# NOTE: Name shortened for readability and defined publicly for easier access
ActionType = TriggeredActionType
"""The type of action triggered by an automation."""


# NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
# so while we allow parsing it from previously saved Automations, we deliberately
# don't currently expose it in the API for creating automations.


class _SavedAction(GQLBase):
    action_type: ActionType


class LaunchJobAction(QueueJobActionFields, _SavedAction):
    typename__: Typename[Literal["QueueJobTriggeredAction"]]
    action_type: Literal[ActionType.QUEUE_JOB] = ActionType.QUEUE_JOB


class NotificationAction(NotificationActionFields, _SavedAction):
    typename__: Typename[Literal["NotificationTriggeredAction"]]
    action_type: Literal[ActionType.NOTIFICATION] = ActionType.NOTIFICATION


class WebhookAction(GenericWebhookActionFields, _SavedAction):
    typename__: Typename[Literal["GenericWebhookTriggeredAction"]]
    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK


class NoOpAction(NoOpActionFields, _SavedAction):
    typename__: Typename[Literal["NoOpTriggeredAction"]]
    action_type: Literal[ActionType.NO_OP] = ActionType.NO_OP


# ------------------------------------------------------------------------------
class _InputAction(GQLBase):
    action_type: ActionType


# Annotations for NotificationActionInput params
# Validation aliases allow arg names from previous `wandb.alert()` API
_NotificationTitleT = Annotated[
    str,
    Field(default="", alias="title"),
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


class DoNotification(NotificationActionInput, _InputAction):
    """Schema for defining a triggered notification action."""

    action_type: Literal[ActionType.NOTIFICATION] = ActionType.NOTIFICATION

    title: _NotificationTitleT = ""
    message: _NotificationMessageT = ""
    severity: _NotificationSeverityT = AlertSeverity.INFO  # type: ignore

    @model_validator(mode="before")
    @classmethod
    def _from_saved(cls, v: Any) -> Any:
        """Convert an action on a saved automation to a new/input action."""
        if pydantic_isinstance(v, NotificationActionFields):
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
        title: _NotificationTitleT = "",
        text: _NotificationMessageT = "",
        level: _NotificationSeverityT = AlertSeverity.INFO,
    ) -> Self:
        """Define a notification action that sends to the given (Slack) integration."""
        from wandb.apis.public.integrations import SlackIntegration

        integration = SlackIntegration.model_validate(integration)
        return cls(
            integration_id=integration.id, title=title, message=text, severity=level
        )


# Annotations for GenericWebhookActionInput params
_WebhookPayloadT = Annotated[
    Optional[SerializedToJson[JsonValue]],
    Field(
        alias=AliasChoices("requestPayload", "request_payload"),
        validation_alias="payload",
    ),
]


class DoWebhook(GenericWebhookActionInput, _InputAction):
    """Schema for defining a triggered webhook action."""

    action_type: Literal[ActionType.GENERIC_WEBHOOK] = ActionType.GENERIC_WEBHOOK

    request_payload: _WebhookPayloadT = None

    @model_validator(mode="before")
    @classmethod
    def _from_saved(cls, v: Any) -> Any:
        """Convert an action on a saved automation to a new/input action."""
        if pydantic_isinstance(v, GenericWebhookActionFields):
            return cls(
                integration_id=v.integration.id, request_payload=v.request_payload
            )
        return v

    @classmethod
    def from_integration(
        cls,
        integration: WebhookIntegration,
        *,
        payload: _WebhookPayloadT = None,
    ) -> Self:
        """Define a webhook action that sends to the given (webhook) integration."""
        from wandb.apis.public.integrations import WebhookIntegration

        integration = WebhookIntegration.model_validate(integration)
        return cls(integration_id=integration.id, request_payload=payload)


class DoNothing(NoOpTriggeredActionInput, _InputAction):
    """Schema for defining a triggered no-op action."""

    action_type: Literal[ActionType.NO_OP] = ActionType.NO_OP

    no_op: bool = True  # prevent exclusion on `.model_dump(exclude_none=True)`
