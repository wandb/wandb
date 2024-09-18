from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum, global_enum
from typing import ClassVar, TypeAlias

from pydantic import AnyUrl, ConfigDict, Field, Json, SecretStr
from typing_extensions import Annotated, Literal, Self, TypeVar, TypedDict

from wandb.sdk.automations._typing import Base64Id, JsonDict, Typename
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
    typename__: Typename[Literal["RunQueue"]]

    id: Base64Id
    name: str


class QueueJobAction(Base):
    typename__: Typename[Literal["QueueJobTriggeredAction"]]

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

    integration: SlackIntegration
    title: str
    message: str
    severity: Severity


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

    integration: WebhookIntegration
    request_payload: Json


AnyAction = Annotated[
    QueueJobAction | NotificationAction | WebhookAction,
    Field(discriminator="typename__", alias="triggeredAction"),
]


# ------------------------------------------------------------------------------
class NewAction(Base, ABC):
    """Base type for Input schemas for creating new automation actions."""

    action_type: ActionType


class NewQueueJob(NewAction):
    """Input schema for creating a QUEUE_JOB action."""

    action_type: Literal[ActionType.QUEUE_JOB] = QUEUE_JOB

    queue_id: Base64Id = Field(alias="queueID")
    template: QueueJobTemplate


class NewNotification(NewAction):
    """Input schema for creating a NOTIFICATION action."""

    action_type: Literal[ActionType.NOTIFICATION] = NOTIFICATION

    integration_id: Base64Id = Field(alias="integrationID")
    title: str
    message: str
    severity: Severity


class NewWebhook(NewAction):
    """Input schema for creating a GENERIC_WEBHOOK action."""

    action_type: Literal[ActionType.GENERIC_WEBHOOK] = GENERIC_WEBHOOK

    integration_id: Base64Id = Field(alias="integrationID")
    request_payload: JsonDict


NewQueueJobConfig = TypedDict(
    "NewQueueJobConfig", {"queue_job_action_input": NewQueueJob}
)
NewNotificationConfig = TypedDict(
    "NewNotificationConfig", {"notification_action_input": NewNotification}
)
NewWebhookConfig = TypedDict(
    "NewWebhookConfig", {"generic_webhook_action_input": NewWebhook}
)
NewActionConfig = NewQueueJobConfig | NewNotificationConfig | NewWebhookConfig

AnyNewAction = Annotated[
    NewQueueJob | NewNotification | NewWebhook,
    Field(discriminator="action_type"),
]
