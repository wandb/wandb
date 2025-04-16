from typing import Union

from pydantic import Field

from wandb._pydantic import GQLBase
from wandb.automations._generated import (
    GenericWebhookIntegrationFields,
    SlackIntegrationFields,
)


class SlackIntegration(SlackIntegrationFields):
    pass


class WebhookIntegration(GenericWebhookIntegrationFields):
    pass


Integration = Union[SlackIntegration, WebhookIntegration]


# For parsing integration instances from paginated responses
class _IntegrationEdge(GQLBase):
    cursor: str
    node: Integration = Field(discriminator="typename__")
