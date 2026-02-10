from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field, TypeAdapter

from ._generated import SlackIntegrationFields, WebhookIntegrationFields


class SlackIntegration(SlackIntegrationFields):
    team_name: str
    """Slack workspace (not W&B team) where this integration will post messages."""

    channel_name: str
    """Slack channel where this integration will post messages."""


class WebhookIntegration(WebhookIntegrationFields):
    name: str
    """The name of this webhook integration."""

    url_endpoint: str
    """The URL that this webhook will POST events to."""


Integration = Annotated[
    Union[SlackIntegration, WebhookIntegration],
    Field(discriminator="typename__"),
]

# INTERNAL USE ONLY: For parsing integrations from paginated responses
IntegrationAdapter: TypeAdapter[Integration] = TypeAdapter(Integration)


__all__ = [
    "Integration",
    "SlackIntegration",
    "WebhookIntegration",
]
