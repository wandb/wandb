from __future__ import annotations

import sys
from contextlib import suppress
from typing import Annotated, Any, ClassVar, Iterable, List, Literal, Union

from pydantic import Field, TypeAdapter, ValidationError
from wandb_gql import gql
from wandb_graphql.language.ast import Document

from wandb.apis.paginator import Paginator
from wandb.sdk.automations._generated import (
    INTEGRATIONS_BY_ENTITY_GQL,
    SLACK_INTEGRATIONS_BY_ENTITY_GQL,
    WEBHOOK_INTEGRATIONS_BY_ENTITY_GQL,
    IntegrationConnectionFields,
    SlackIntegrationConnectionFields,
    SlackIntegrationFields,
    Typename,
    WebhookIntegrationConnectionFields,
    WebhookIntegrationFields,
)

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


class SlackIntegration(SlackIntegrationFields):
    typename__: Typename[Literal["SlackIntegration"]]


class WebhookIntegration(WebhookIntegrationFields):
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
        with suppress(AttributeError):  # AttributeError if last_page is None
            return self.last_response.page_info.has_next_page
        return True

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page."""
        with suppress(AttributeError):  # AttributeError if last_page is None
            return self.last_response.page_info.end_cursor
        return None

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
    QUERY: ClassVar[Document] = gql(WEBHOOK_INTEGRATIONS_BY_ENTITY_GQL)

    last_response: WebhookIntegrationConnectionFields | None

    @property
    def more(self) -> bool:
        """Whether there are more Integrations to fetch."""
        with suppress(AttributeError):  # AttributeError if last_page is None
            return self.last_response.page_info.has_next_page
        return True

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page."""
        with suppress(AttributeError):  # AttributeError if last_page is None
            return self.last_response.page_info.end_cursor
        return None

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        data: dict[str, Any] = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        try:
            page_data = data["entity"]["integrations"]
            self.last_response = WebhookIntegrationConnectionFields.model_validate(
                page_data
            )
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[WebhookIntegration]:
        """Parse the page data into a list of Integrations."""
        page = self.last_response
        return WebhookIntegrationListAdapter.validate_python(
            edge.node for edge in page.edges
        )


class SlackIntegrations(Paginator[SlackIntegration]):
    QUERY: ClassVar[Document] = gql(SLACK_INTEGRATIONS_BY_ENTITY_GQL)

    last_response: SlackIntegrationConnectionFields | None

    @property
    def more(self) -> bool:
        """Whether there are more Integrations to fetch."""
        with suppress(AttributeError):  # AttributeError if last_page is None
            return self.last_response.page_info.has_next_page
        return True

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page."""
        with suppress(AttributeError):  # AttributeError if last_page is None
            return self.last_response.page_info.end_cursor
        return None

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
        return SlackIntegrationListAdapter.validate_python(
            edge.node for edge in page.edges
        )
