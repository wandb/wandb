from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Union

from pydantic import AnyUrl, Field, SecretStr
from typing_extensions import Annotated, Literal

from wandb.sdk.automations._typing import Base64Id, JsonDict, TypenameField
from wandb.sdk.automations.base import Base


class SeverityLevel(StrEnum):
    ERROR = "ERROR"
    INFO = "INFO"
    WARN = "WARN"


class RunQueue(Base):
    typename__: TypenameField[Literal["RunQueue"]]

    id: Base64Id
    name: str


class QueueJobAction(Base):
    typename__: TypenameField[Literal["QueueJobTriggeredAction"]]

    queue: RunQueue | None
    template: JsonDict  # TODO: parse


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
    severity: SeverityLevel


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
    request_payload: JsonDict = Field(alias="requestPayload")


AnyAction = Annotated[
    Union[
        QueueJobAction,
        NotificationAction,
        WebhookAction,
    ],
    Field(discriminator="typename__", alias="triggeredAction"),
]
