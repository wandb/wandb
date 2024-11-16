"""Actions that are triggered by W&B Automations."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from pydantic import AliasChoices, Field, JsonValue

from ._base import Base, Base64Id, SerializedToJson, Typename
from ._generated import (
    AlertSeverity,
    GenericWebhookActionInput,
    NotificationActionInput,
    QueueJobAction,
    RunQueue,
    SlackIntegration,
    TriggeredActionType,
    WebhookIntegration,
)

if TYPE_CHECKING:
    from wandb.sdk import AlertLevel

if sys.version_info >= (3, 12):
    from typing import Annotated, Literal, Self
else:
    from typing_extensions import Annotated, Literal, Self


class LaunchJobAction(QueueJobAction):  # Renamed for consistency with exisitng APIs
    typename__: Typename[Literal["QueueJobTriggeredAction"]]

    queue: RunQueue | None  # type: ignore[assignment]  # codegen generates redundant(?) subclass for field type
    template: SerializedToJson[dict[str, JsonValue]]


class NotificationAction(Base):
    typename__: Typename[Literal["NotificationTriggeredAction"]]

    integration: SlackIntegration
    title: str
    message: str
    severity: AlertSeverity


class WebhookAction(Base):
    typename__: Typename[Literal["GenericWebhookTriggeredAction"]]

    integration: WebhookIntegration
    request_payload: SerializedToJson[JsonValue]


# ------------------------------------------------------------------------------
class DoNotification(NotificationActionInput):
    """Input schema for creating a NOTIFICATION action."""

    action_type: Literal[TriggeredActionType.NOTIFICATION] = Field(
        TriggeredActionType.NOTIFICATION, frozen=True
    )

    integration_id: Base64Id = Field(alias="integrationID")
    title: str = ""
    message: str = Field(
        default="",
        # For consistency/compatibility with existing wandb.alert() API
        validation_alias=AliasChoices("text", "message"),
        serialization_alias="message",
    )
    severity: AlertSeverity = Field(
        default=AlertSeverity.INFO,
        # For consistency/compatibility with existing wandb.alert() API
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

        integration = Api()._team_slack_integration(entity)
        return cls(
            integration_id=integration.id,
            title=title,
            text=text,
            level=level,
        )


class DoWebhook(GenericWebhookActionInput):
    """Input schema for creating a GENERIC_WEBHOOK action."""

    action_type: Annotated[
        Literal[TriggeredActionType.GENERIC_WEBHOOK],
        Field(TriggeredActionType.GENERIC_WEBHOOK, frozen=True),
    ]

    integration_id: Base64Id = Field(alias="integrationID")
    request_payload: SerializedToJson[JsonValue]


class DoLaunchJob(Base):
    """Input schema for creating a QUEUE_JOB action."""

    action_type: Annotated[
        Literal[TriggeredActionType.QUEUE_JOB],
        Field(TriggeredActionType.QUEUE_JOB, frozen=True),
    ]

    queue_id: Base64Id = Field(alias="queueID")
    template: SerializedToJson[dict[str, JsonValue]]

    # TODO: Warn about deprecation on instantiating a new QueueJob as part of an automation
