from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Union

from pydantic import AnyUrl, Field, SecretStr
from typing_extensions import Annotated, Literal

from wandb.sdk.automations._typing import Base64Id, JsonDict
from wandb.sdk.automations.base import Base


class SeverityLevel(StrEnum):
    ERROR = "ERROR"
    INFO = "INFO"
    WARN = "WARN"


class RunQueue(Base):
    typename__: Literal["RunQueue"] = Field(repr=False, alias="__typename")
    id: Base64Id
    name: str


class QueueJobAction(Base):
    typename__: Literal["QueueJobTriggeredAction"] = Field(
        repr=False, alias="__typename"
    )
    queue: RunQueue
    template: JsonDict  # TODO: parse


class SlackIntegration(Base):
    typename__: Literal["SlackIntegration"] = Field(repr=False, alias="__typename")
    id: Base64Id


class NotificationAction(Base):
    typename__: Literal["NotificationTriggeredAction"] = Field(
        repr=False, alias="__typename"
    )
    integration: SlackIntegration
    title: str
    message: str
    severity: SeverityLevel


class WebhookIntegration(Base):
    typename__: Literal["GenericWebhookIntegration"] = Field(
        repr=False, alias="__typename"
    )
    id: Base64Id
    name: str
    url_endpoint: AnyUrl

    access_token_ref: SecretStr | None
    secret_ref: SecretStr | None

    created_at: datetime


class WebhookAction(Base):
    typename__: Literal["GenericWebhookTriggeredAction"] = Field(
        repr=False, alias="__typename"
    )
    integration: WebhookIntegration
    request_payload: JsonDict = Field(alias="requestPayload")


AnyAction = Annotated[
    Union[
        QueueJobAction,
        NotificationAction,
        WebhookAction,
    ],
    Field(alias="triggeredAction"),
]
