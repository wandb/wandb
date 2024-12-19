"""Actions that are triggered by W&B Automations."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from pydantic import AliasChoices, Field, JsonValue

from ._base import Base64Id, SerializedToJson, Typename
from ._generated import (
    AlertSeverity,
    GenericWebhookActionInput,
    NotificationActionFields,
    NotificationActionInput,
    QueueJobActionFields,
    RunQueue,
    SlackIntegration,
    TriggeredActionType,
    WebhookActionFields,
    WebhookIntegration,
)

if TYPE_CHECKING:
    from wandb.sdk import AlertLevel

if sys.version_info >= (3, 12):
    from typing import Annotated, Literal, Self
else:
    from typing_extensions import Annotated, Literal, Self


# NOTE: Enum is aliased to a shorter name for readability,
# in a public module for easier access
ActionType = TriggeredActionType
"""The type of action triggered by an automation."""


class LaunchJobAction(QueueJobActionFields):
    typename__: Typename[Literal["QueueJobTriggeredAction"]]

    queue: RunQueue | None  # type: ignore[assignment]  # codegen generates redundant(?) subclass for field type
    template: SerializedToJson[dict[str, JsonValue]]


class NotificationAction(NotificationActionFields):
    typename__: Typename[Literal["NotificationTriggeredAction"]]

    integration: SlackIntegration
    title: str
    message: str
    severity: AlertSeverity


class WebhookAction(WebhookActionFields):
    typename__: Typename[Literal["GenericWebhookTriggeredAction"]]

    integration: WebhookIntegration
    request_payload: SerializedToJson[JsonValue]


# ------------------------------------------------------------------------------
class DoNotification(NotificationActionInput):
    """Schema for defining a triggered notification action."""

    action_type: Annotated[
        Literal[ActionType.NOTIFICATION],
        Field(ActionType.NOTIFICATION, frozen=True),
    ]

    integration_id: Base64Id = Field(alias="integrationID")
    title: str = ""
    message: str = Field(
        # Aliases for consistency/compatibility with existing wandb.alert() API
        default="",
        validation_alias=AliasChoices("text", "message"),
        serialization_alias="message",
    )
    severity: AlertSeverity = Field(
        # Aliases for consistency/compatibility with existing wandb.alert() API
        default=AlertSeverity.INFO,
        validation_alias=AliasChoices("level", "severity"),
        serialization_alias="severity",
    )

    @classmethod
    def from_integration(
        cls,
        integration: SlackIntegration,
        *,
        title: str = "",
        text: str = "",
        level: AlertSeverity | AlertLevel | str = AlertSeverity.INFO,
    ) -> Self:
        """Define a Notification action that sends to the given (Slack) integration."""
        return cls(integration_id=integration.id, title=title, text=text, level=level)

    @classmethod
    def for_team(
        cls,
        entity: str,
        *,
        title: str = "",
        text: str = "",
        level: AlertSeverity | AlertLevel | str = AlertSeverity.INFO,
    ) -> Self:
        from wandb.apis.public.api import Api

        integration = Api().slack_integration(entity)
        return cls(
            integration_id=integration.id,
            title=title,
            text=text,
            level=level,
        )


class DoWebhook(GenericWebhookActionInput):
    """Schema for defining a triggered webhook action."""

    action_type: Annotated[
        Literal[ActionType.GENERIC_WEBHOOK],
        Field(ActionType.GENERIC_WEBHOOK, frozen=True),
    ]

    integration_id: Base64Id = Field(alias="integrationID")
    request_payload: SerializedToJson[JsonValue]

    @classmethod
    def from_integration(
        cls,
        integration: WebhookIntegration,
        *,
        request_payload: JsonValue,
    ) -> Self:
        """Define a Notification action that sends to the given (Slack) integration."""
        return cls(integration_id=integration.id, request_payload=request_payload)


# NOTE: `QueueJobActionInput` for defining a Launch job is deprecated,
# so we deliberately don't currently expose it in the API for creating automations.
