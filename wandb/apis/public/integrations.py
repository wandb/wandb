"""W&B Public API for integrations.

This module provides classes for interacting with W&B integrations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

from typing_extensions import override
from wandb_gql import gql

from wandb.apis.paginator import Paginator

if TYPE_CHECKING:
    from wandb_graphql.language.ast import Document

    from wandb._pydantic import Connection
    from wandb.apis.paginator import _Client
    from wandb.automations import Integration, SlackIntegration, WebhookIntegration
    from wandb.automations._generated import (
        SlackIntegrationFields,
        WebhookIntegrationFields,
    )


class Integrations(Paginator["Integration"]):
    """An lazy iterator of `Integration` objects."""

    last_response: Connection[SlackIntegrationFields | WebhookIntegrationFields] | None
    _query: Document

    def __init__(self, client: _Client, variables: dict[str, Any], per_page: int = 50):
        from wandb.automations._generated import INTEGRATIONS_BY_ENTITY_GQL

        super().__init__(client, variables, per_page=per_page)
        self._query = gql(INTEGRATIONS_BY_ENTITY_GQL)

    @property
    def more(self) -> bool:
        """Whether there are more Integrations to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        return (conn := self.last_response) is None or conn.has_next

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page.

        <!-- lazydoc-ignore: internal -->
        """
        return conn.next_cursor if (conn := self.last_response) else None

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import IntegrationsByEntity

        data = self.client.execute(self._query, variable_values=self.variables)
        result = IntegrationsByEntity.model_validate(data)
        if not ((entity := result.entity) and (conn := entity.integrations)):
            raise ValueError("Unexpected response data")

        self.last_response = Connection.model_validate(conn)

    def convert_objects(self) -> Iterable[Integration]:
        """Parse the page data into a list of integrations."""
        from wandb.automations.integrations import IntegrationListAdapter

        if (conn := self.last_response) is None:
            return []
        return IntegrationListAdapter.validate_python(conn.nodes())


class WebhookIntegrations(Paginator["WebhookIntegration"]):
    """An lazy iterator of `WebhookIntegration` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    last_response: Connection[WebhookIntegrationFields] | None
    _query: Document

    def __init__(self, client: _Client, variables: dict[str, Any], per_page: int = 50):
        from wandb.automations._generated import WEBHOOK_INTEGRATIONS_BY_ENTITY_GQL

        super().__init__(client, variables, per_page=per_page)
        self._query = gql(WEBHOOK_INTEGRATIONS_BY_ENTITY_GQL)

    @property
    def more(self) -> bool:
        """Whether there are more webhook integrations to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        return (conn := self.last_response) is None or conn.has_next

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page.

        <!-- lazydoc-ignore: internal -->
        """
        return conn.next_cursor if (conn := self.last_response) else None

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import WebhookIntegrationsByEntity

        data = self.client.execute(self._query, variable_values=self.variables)
        result = WebhookIntegrationsByEntity.model_validate(data)

        if not ((entity := result.entity) and (conn := entity.integrations)):
            raise ValueError("Unexpected response data")

        self.last_response = Connection.model_validate(conn)

    def convert_objects(self) -> Iterable[WebhookIntegration]:
        """Parse the page data into a list of webhook integrations."""
        from wandb.automations import WebhookIntegration

        typename = "GenericWebhookIntegration"
        return [
            # Filter on typename__ needed because the GQL response still
            # includes all integration types
            WebhookIntegration.model_validate(node)
            for node in self.last_response.nodes()
            if (node.typename__ == typename)
        ]


class SlackIntegrations(Paginator["SlackIntegration"]):
    """An lazy iterator of `SlackIntegration` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    last_response: Connection[SlackIntegrationFields] | None
    _query: Document

    def __init__(self, client: _Client, variables: dict[str, Any], per_page: int = 50):
        from wandb.automations._generated import SLACK_INTEGRATIONS_BY_ENTITY_GQL

        super().__init__(client, variables, per_page=per_page)
        self._query = gql(SLACK_INTEGRATIONS_BY_ENTITY_GQL)

    @property
    def more(self) -> bool:
        """Whether there are more Slack integrations to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        return (conn := self.last_response) is None or conn.has_next

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page.

        <!-- lazydoc-ignore: internal -->
        """
        return conn.next_cursor if (conn := self.last_response) else None

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import SlackIntegrationsByEntity

        data = self.client.execute(self._query, variable_values=self.variables)
        result = SlackIntegrationsByEntity.model_validate(data)

        if not ((entity := result.entity) and (conn := entity.integrations)):
            raise ValueError("Unexpected response data")

        self.last_response = Connection.model_validate(conn)

    def convert_objects(self) -> Iterable[SlackIntegration]:
        """Parse the page data into a list of Slack integrations."""
        from wandb.automations import SlackIntegration

        typename = "SlackIntegration"
        return [
            # Filter on typename__ needed because the GQL response still
            # includes all integration types
            SlackIntegration.model_validate(node)
            for node in self.last_response.nodes()
            if (node.typename__ == typename)
        ]
