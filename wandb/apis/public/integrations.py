"""W&B Public API for integrations.

This module provides classes for interacting with W&B integrations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Union

from typing_extensions import override
from wandb_gql import gql

from wandb.apis.paginator import RelayPaginator

if TYPE_CHECKING:
    from wandb_graphql.language.ast import Document

    from wandb._pydantic import Connection
    from wandb.apis.public.api import RetryingClient
    from wandb.automations import Integration, SlackIntegration, WebhookIntegration
    from wandb.automations._generated import (
        SlackIntegrationFields,
        WebhookIntegrationFields,
    )

    IntegrationFields = Union[SlackIntegrationFields, WebhookIntegrationFields]


class Integrations(RelayPaginator["IntegrationFields", "Integration"]):
    """A lazy iterator of `Integration` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    QUERY: ClassVar[Document | None] = None
    last_response: Connection[IntegrationFields] | None

    def __init__(
        self,
        client: RetryingClient,
        variables: dict[str, Any],
        per_page: int = 50,
    ):
        if self.QUERY is None:
            from wandb.automations._generated import INTEGRATIONS_BY_ENTITY_GQL

            type(self).QUERY = gql(INTEGRATIONS_BY_ENTITY_GQL)

        super().__init__(client, variables=variables, per_page=per_page)

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import IntegrationsByEntity

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = IntegrationsByEntity.model_validate(data)
        if not ((entity := result.entity) and (conn := entity.integrations)):
            raise ValueError("Unexpected response data")
        self.last_response = Connection.model_validate(conn)

    def _convert(self, node: IntegrationFields) -> Integration:
        from wandb.automations.integrations import IntegrationAdapter

        return IntegrationAdapter.validate_python(node)


# The paginators below filter on `typename__` since the GQL response still
# includes all `Integration` types. Applying a `@skip/@include` directive
# does not change this. Restricting results to a single type requires
# a client-side filter.
class WebhookIntegrations(Integrations):
    """A lazy iterator of `WebhookIntegration` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    def _convert(self, node: IntegrationFields) -> WebhookIntegration:
        return node if (node.typename__ == "GenericWebhookIntegration") else None


class SlackIntegrations(Integrations):
    """A lazy iterator of `SlackIntegration` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    def _convert(self, node: IntegrationFields) -> SlackIntegration:
        return node if (node.typename__ == "SlackIntegration") else None
