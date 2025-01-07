from __future__ import annotations

import sys
from typing import Any, ClassVar, Iterable, List, Literal, Union

from pydantic import Field, TypeAdapter, ValidationError
from wandb_gql import gql
from wandb_graphql.language.ast import Document

from wandb.apis.paginator import Paginator
from wandb.sdk.automations._generated import (
    GENERIC_WEBHOOK_INTEGRATIONS_BY_ENTITY_GQL,
    INTEGRATIONS_BY_ENTITY_GQL,
    SLACK_INTEGRATIONS_BY_ENTITY_GQL,
    GenericWebhookIntegrationConnectionFields,
    GenericWebhookIntegrationFields,
    IntegrationConnectionFields,
    SlackIntegrationConnectionFields,
    SlackIntegrationFields,
    Typename,
)

if sys.version_info >= (3, 12):
    from typing import Annotated, override
else:
    from typing_extensions import Annotated, override


class SlackIntegration(SlackIntegrationFields):
    typename__: Typename[Literal["SlackIntegration"]]


class WebhookIntegration(GenericWebhookIntegrationFields):
    typename__: Typename[Literal["GenericWebhookIntegration"]]


Integration = Annotated[
    Union[SlackIntegration, WebhookIntegration],
    Field(discriminator="typename__"),
]


SlackIntegrationListAdapter = TypeAdapter(List[SlackIntegration])
WebhookIntegrationListAdapter = TypeAdapter(List[WebhookIntegration])
IntegrationListAdapter = TypeAdapter(List[Integration])


class Integrations(Paginator[Integration]):
    QUERY: ClassVar[Document] = gql(INTEGRATIONS_BY_ENTITY_GQL)

    last_response: IntegrationConnectionFields | None

    @property
    def more(self) -> bool:
        """Whether there are more Integrations to fetch."""
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
        data: dict[str, Any] = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        try:
            page_data = data["entity"]["integrations"]
            self.last_response = IntegrationConnectionFields.model_validate(page_data)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[Integration]:
        """Parse the page data into a list of Integrations."""
        page = self.last_response
        return IntegrationListAdapter.validate_python(edge.node for edge in page.edges)


class WebhookIntegrations(Paginator[WebhookIntegration]):
    QUERY: ClassVar[Document] = gql(GENERIC_WEBHOOK_INTEGRATIONS_BY_ENTITY_GQL)

    last_response: GenericWebhookIntegrationConnectionFields | None

    @property
    def more(self) -> bool:
        """Whether there are more Integrations to fetch."""
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
        data: dict[str, Any] = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        try:
            page_data = data["entity"]["integrations"]
            self.last_response = (
                GenericWebhookIntegrationConnectionFields.model_validate(page_data)
            )
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[WebhookIntegration]:
        """Parse the page data into a list of Integrations."""
        page = self.last_response
        return [
            WebhookIntegration.model_validate_json(edge.node.model_dump_json())
            for edge in page.edges
        ]


class SlackIntegrations(Paginator[SlackIntegration]):
    QUERY: ClassVar[Document] = gql(SLACK_INTEGRATIONS_BY_ENTITY_GQL)

    last_response: SlackIntegrationConnectionFields | None

    @property
    def more(self) -> bool:
        """Whether there are more Integrations to fetch."""
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
        data: dict[str, Any] = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        try:
            page_data = data["entity"]["integrations"]
            self.last_response = SlackIntegrationConnectionFields.model_validate(
                page_data
            )
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> list[SlackIntegration]:
        """Parse the page data into a list of Integrations."""
        page = self.last_response
        return [
            SlackIntegration.model_validate_json(edge.node.model_dump_json())
            for edge in page.edges
        ]
