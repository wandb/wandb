from typing import Union

from pydantic import Field
from typing_extensions import Annotated

from wandb._pydantic import GQLBase
from wandb.automations._generated import (
    GenericWebhookIntegrationFields,
    SlackIntegrationFields,
)


class SlackIntegration(SlackIntegrationFields):
    pass


class WebhookIntegration(GenericWebhookIntegrationFields):
    pass


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
