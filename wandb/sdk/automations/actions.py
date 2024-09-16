from __future__ import annotations

from datetime import datetime
from enum import StrEnum, global_enum
from typing import TypeAlias

from pydantic import AnyUrl, Field, Json, SecretStr
from typing_extensions import Annotated, Literal

from wandb.sdk.automations._typing import Base64Id, JsonDict, TypenameField
from wandb.sdk.automations.base import Base

QueueJobTemplate: TypeAlias = JsonDict  # TODO: parse


@global_enum
class ActionType(StrEnum):
    GENERIC_WEBHOOK = "GENERIC_WEBHOOK"
    NOTIFICATION = "NOTIFICATION"
    QUEUE_JOB = "QUEUE_JOB"


GENERIC_WEBHOOK = ActionType.GENERIC_WEBHOOK
NOTIFICATION = ActionType.NOTIFICATION
QUEUE_JOB = ActionType.QUEUE_JOB


class Severity(StrEnum):
    ERROR = "ERROR"
    INFO = "INFO"
    WARN = "WARN"


# ------------------------------------------------------------------------------
class RunQueue(Base):
    typename__: TypenameField[Literal["RunQueue"]]

    id: Base64Id
    name: str


class QueueJobAction(Base):
    typename__: TypenameField[Literal["QueueJobTriggeredAction"]]

    queue: RunQueue | None
    template: QueueJobTemplate


# ------------------------------------------------------------------------------
class SlackIntegration(Base):
    typename__: TypenameField[Literal["SlackIntegration"]]

    id: Base64Id
    team_name: str
    channel_name: str


class NotificationAction(Base):
    typename__: TypenameField[Literal["NotificationTriggeredAction"]]

    integration: SlackIntegration
    title: str
    message: str
    severity: Severity


# ------------------------------------------------------------------------------
class WebhookIntegration(Base):
    typename__: TypenameField[Literal["GenericWebhookIntegration"]]

    id: Base64Id
    name: str
    url_endpoint: AnyUrl

    access_token_ref: SecretStr | None
    secret_ref: SecretStr | None

    created_at: datetime


class WebhookAction(Base):
    typename__: TypenameField[Literal["GenericWebhookTriggeredAction"]]

    integration: WebhookIntegration
    request_payload: Json


AnyAction = Annotated[
    QueueJobAction | NotificationAction | WebhookAction,
    Field(discriminator="typename__", alias="triggeredAction"),
]


# ------------------------------------------------------------------------------
class NewActionInput(Base):
    """Base type for Input schemas for creating new automation actions."""


class NewActionConfig(Base):
    """Base type for action config schemas for creating new automation actions."""


class NewQueueJobActionInput(NewActionInput):
    """Input schema for creating a QUEUE_JOB action."""

    queue_id: Base64Id = Field(alias="queueID")
    template: QueueJobTemplate


class NewQueueJobConfig(NewActionConfig):
    queue_job_action_input: NewQueueJobActionInput


class NewNotificationActionInput(NewActionInput):
    """Input schema for creating a NOTIFICATION action."""

    integration_id: Base64Id = Field(alias="integrationID")
    title: str
    message: str
    severity: Severity


class NewNotificationConfig(NewActionConfig):
    notification_action_input: NewNotificationActionInput


class NewWebhookActionInput(NewActionInput):
    """Input schema for creating a GENERIC_WEBHOOK action."""

    integration_id: Base64Id = Field(alias="integrationID")
    request_payload: JsonDict


class NewWebhookConfig(NewActionConfig):
    generic_webhook_action_input: NewWebhookActionInput
