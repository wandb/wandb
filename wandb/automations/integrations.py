from typing import Union

from pydantic import Field
from typing_extensions import Annotated

from wandb._pydantic import GQLBase
from wandb.automations._generated import (
    GenericWebhookIntegrationFields,
    SlackIntegrationFields,
)


class SlackIntegration(SlackIntegrationFields):
    team_name: str
    """The name of the Slack workspace (not the W&B team) that this integration is associated with."""

    channel_name: str
    """The name of the Slack channel that this integration will post messages to."""


class WebhookIntegration(GenericWebhookIntegrationFields):
    name: str
    """The name of this webhook integration."""

    url_endpoint: str
    """The URL that this webhook will POST events to."""


Integration = Annotated[
    Union[SlackIntegration, WebhookIntegration],
    Field(discriminator="typename__"),
]


# For parsing integration instances from paginated responses
class _IntegrationEdge(GQLBase):
    cursor: str
    node: Integration


__all__ = [
    "Integration",
    "SlackIntegration",
    "WebhookIntegration",
]
