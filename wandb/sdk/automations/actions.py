from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

from pydantic import AnyUrl, ConfigDict, Field, SecretStr
from typing_extensions import Annotated, Literal

from wandb.sdk.automations._typing import Base64Id, JsonDict, TypenameField
from wandb.sdk.automations.base import Base

QueueJobTemplate: TypeAlias = JsonDict  # TODO: parse


class AlertSeverity(StrEnum):
    ERROR = "ERROR"
    INFO = "INFO"
    WARN = "WARN"


class ActionInput(Base):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )


# ------------------------------------------------------------------------------
class RunQueue(Base):
    typename__: TypenameField[Literal["RunQueue"]]

    id: Base64Id
    name: str


class QueueJobAction(Base):
    typename__: TypenameField[Literal["QueueJobTriggeredAction"]]

    queue: RunQueue | None
    template: QueueJobTemplate


class QueueJobActionInput(ActionInput):
    """Input schema for creating a QUEUE_JOB action."""

    queue_id: Base64Id = Field(alias="queueID")
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
    severity: AlertSeverity


class NotificationActionInput(ActionInput):
    """Input schema for creating a NOTIFICATION action."""

    integration_id: Base64Id = Field(alias="integrationID")
    title: str
    message: str
    severity: AlertSeverity


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
    request_payload: JsonDict


class WebhookActionInput(ActionInput):
    """Input schema for creating a GENERIC_WEBHOOK action."""

    integration_id: Base64Id = Field(alias="integrationID")
    request_payload: JsonDict


AnyAction = Annotated[
    QueueJobAction | NotificationAction | WebhookAction,
    Field(discriminator="typename__", alias="triggeredAction"),
]
