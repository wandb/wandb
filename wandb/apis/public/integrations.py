"""W&B Public API for integrations.

This module provides classes for interacting with W&B integrations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

from pydantic import ValidationError
from typing_extensions import override
from wandb_gql import gql
from wandb_graphql.language.ast import Document

from wandb.apis.paginator import Paginator

if TYPE_CHECKING:
    from wandb.apis.paginator import _Client
    from wandb.automations import Integration, SlackIntegration, WebhookIntegration
    from wandb.automations._generated import (
        GenericWebhookIntegrationConnectionFields,
        IntegrationConnectionFields,
        SlackIntegrationConnectionFields,
    )


class Integrations(Paginator["Integration"]):
    """An lazy iterator of `Integration` objects."""

    last_response: IntegrationConnectionFields | None
    _query: Document

    def __init__(self, client: _Client, variables: dict[str, Any], per_page: int = 50):
        from wandb.automations._generated import INTEGRATIONS_BY_ENTITY_GQL

        super().__init__(client, variables, per_page=per_page)
        # All integrations for entity
        self._query = gql(INTEGRATIONS_BY_ENTITY_GQL)

    @property
    def more(self) -> bool:
        """Whether there are more Integrations to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            return None
        return self.last_response.page_info.end_cursor

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        from wandb.automations._generated import IntegrationConnectionFields

        data: dict[str, Any] = self.client.execute(
            self._query, variable_values=self.variables
        )
        try:
            page_data = data["entity"]["integrations"]
            self.last_response = IntegrationConnectionFields.model_validate(page_data)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[Integration]:
        """Parse the page data into a list of integrations."""
        from wandb.automations.integrations import _IntegrationEdge

        page = self.last_response
        return [_IntegrationEdge.model_validate(edge).node for edge in page.edges]


class WebhookIntegrations(Paginator["WebhookIntegration"]):
    """An lazy iterator of `WebhookIntegration` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    last_response: GenericWebhookIntegrationConnectionFields | None
    _query: Document

    def __init__(self, client: _Client, variables: dict[str, Any], per_page: int = 50):
        from wandb.automations._generated import (
            GENERIC_WEBHOOK_INTEGRATIONS_BY_ENTITY_GQL,
        )

        super().__init__(client, variables, per_page=per_page)
        # Webhook integrations for entity
        self._query = gql(GENERIC_WEBHOOK_INTEGRATIONS_BY_ENTITY_GQL)

    @property
    def more(self) -> bool:
        """Whether there are more webhook integrations to fetch."""
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page."""
        if self.last_response is None:
            return None
        return self.last_response.page_info.end_cursor

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        from wandb.automations._generated import (
            GenericWebhookIntegrationConnectionFields,
        )

        data: dict[str, Any] = self.client.execute(
            self._query, variable_values=self.variables
        )
        try:
            page_data = data["entity"]["integrations"]
            self.last_response = (
                GenericWebhookIntegrationConnectionFields.model_validate(page_data)
            )
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[WebhookIntegration]:
        """Parse the page data into a list of webhook integrations."""
        from wandb.automations import WebhookIntegration

        typename = "GenericWebhookIntegration"
        return [
            # Filter on typename__ needed because the GQL response still
            # includes all integration types
            WebhookIntegration.model_validate(node)
            for edge in self.last_response.edges
            if (node := edge.node) and (node.typename__ == typename)
        ]


class SlackIntegrations(Paginator["SlackIntegration"]):
    """An lazy iterator of `SlackIntegration` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    last_response: SlackIntegrationConnectionFields | None
    _query: Document

    def __init__(self, client: _Client, variables: dict[str, Any], per_page: int = 50):
        from wandb.automations._generated import SLACK_INTEGRATIONS_BY_ENTITY_GQL

        super().__init__(client, variables, per_page=per_page)
        # Slack integrations for entity
        self._query = gql(SLACK_INTEGRATIONS_BY_ENTITY_GQL)

    @property
    def more(self) -> bool:
        """Whether there are more Slack integrations to fetch."""
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page."""
        if self.last_response is None:
            return None
        return self.last_response.page_info.end_cursor

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        from wandb.automations._generated import SlackIntegrationConnectionFields

        data: dict[str, Any] = self.client.execute(
            self._query, variable_values=self.variables
        )
        try:
            page_data = data["entity"]["integrations"]
            self.last_response = SlackIntegrationConnectionFields.model_validate(
                page_data
            )
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[SlackIntegration]:
        """Parse the page data into a list of Slack integrations."""
        from wandb.automations import SlackIntegration

        typename = "SlackIntegration"
        return [
            # Filter on typename__ needed because the GQL response still
            # includes all integration types
            SlackIntegration.model_validate(node)
            for edge in self.last_response.edges
            if (node := edge.node) and (node.typename__ == typename)
        ]
