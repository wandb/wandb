"""Actions that are triggered by W&B Automations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeAlias

from pydantic import AliasChoices, AnyUrl, Field, Json, SecretStr
from typing_extensions import Annotated, Literal, Self

from wandb.sdk.automations._base import Base
from wandb.sdk.automations._generated.enums import AlertSeverity, TriggeredActionType
from wandb.sdk.automations._generated.fragments import RunQueue
from wandb.sdk.automations._typing import Base64Id, JsonDict, Typename

QueueJobTemplate: TypeAlias = JsonDict  # TODO: parse


# ------------------------------------------------------------------------------
# class RunQueue(Base):
#     typename__: Typename[Literal["RunQueue"]]
#
#     id: Base64Id
#     name: str


class QueueJobAction(Base):
    typename__: Typename[Literal["QueueJobTriggeredAction"]]

    action_type: Literal[TriggeredActionType.QUEUE_JOB] = TriggeredActionType.QUEUE_JOB

    queue: RunQueue | None
    template: QueueJobTemplate


# ------------------------------------------------------------------------------
class SlackIntegration(Base):
    typename__: Typename[Literal["SlackIntegration"]]

    id: Base64Id
    team_name: str
    channel_name: str


class NotificationAction(Base):
    typename__: Typename[Literal["NotificationTriggeredAction"]]

    action_type: Literal[TriggeredActionType.NOTIFICATION] = (
        TriggeredActionType.NOTIFICATION
    )

    integration: SlackIntegration
    title: str
    message: str
    severity: AlertSeverity


# ------------------------------------------------------------------------------
class WebhookIntegration(Base):
    typename__: Typename[Literal["GenericWebhookIntegration"]]

    id: Base64Id
    name: str
    url_endpoint: AnyUrl

    access_token_ref: SecretStr | None = Field(repr=False)
    secret_ref: SecretStr | None = Field(repr=False)

    created_at: datetime = Field(repr=False)


class WebhookAction(Base):
    typename__: Typename[Literal["GenericWebhookTriggeredAction"]]

    action_type: Literal[TriggeredActionType.GENERIC_WEBHOOK] = (
        TriggeredActionType.GENERIC_WEBHOOK
    )

    integration: WebhookIntegration
    request_payload: Json


AnyAction = Annotated[
    QueueJobAction | NotificationAction | WebhookAction,
    Field(
        discriminator="typename__",
        alias="triggeredAction",
        validation_alias=AliasChoices("triggeredAction", "triggered_action"),
    ),
]


# ------------------------------------------------------------------------------
class NewQueueJob(Base):
    """Input schema for creating a QUEUE_JOB action."""

    action_type: Literal[TriggeredActionType.QUEUE_JOB] = TriggeredActionType.QUEUE_JOB

    queue_id: Base64Id = Field(alias="queueID")
    template: QueueJobTemplate


class NewNotification(Base):
    """Input schema for creating a NOTIFICATION action."""

    action_type: Literal[TriggeredActionType.NOTIFICATION] = (
        TriggeredActionType.NOTIFICATION
    )

    integration_id: Base64Id = Field(alias="integrationID")
    title: str = ""
    message: str = ""
    severity: AlertSeverity = AlertSeverity.INFO

    @classmethod
    def from_integration(cls, integration: SlackIntegration, **kwargs: Any) -> Self:
        """Define a Notification action that sends to the given (Slack) integration."""
        return cls(integration_id=integration.id, **kwargs)

    @classmethod
    def for_team(cls, entity: str, **kwargs: Any) -> Self:
        from wandb.sdk.automations.api import team_slack_integration

        return cls.model_validate(
            dict(integration_id=team_slack_integration(entity).id, **kwargs)
        )


class NewWebhook(Base):
    """Input schema for creating a GENERIC_WEBHOOK action."""

    action_type: Literal[TriggeredActionType.GENERIC_WEBHOOK] = (
        TriggeredActionType.GENERIC_WEBHOOK
    )

    integration_id: Base64Id = Field(alias="integrationID")
    request_payload: JsonDict
