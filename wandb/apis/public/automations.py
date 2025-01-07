from __future__ import annotations

import sys
from contextlib import suppress
from itertools import chain
from typing import Any, ClassVar, Iterable, List

from pydantic import TypeAdapter, ValidationError
from wandb_gql import gql
from wandb_graphql.language.ast import Document

from wandb.apis.paginator import Paginator
from wandb.sdk.automations import Automation
from wandb.sdk.automations._generated import (
    GET_TRIGGERS_BY_ENTITY_GQL,
    GET_TRIGGERS_GQL,
    ProjectConnectionFields,
)

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

AutomationListAdapter = TypeAdapter(List[Automation])


class AutomationsByEntity(Paginator[Automation]):
    QUERY: ClassVar[Document] = gql(GET_TRIGGERS_BY_ENTITY_GQL)

    last_response: ProjectConnectionFields | None

    @property
    def more(self) -> bool:
        """Whether there are more items to fetch."""
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
        """Fetch the raw response data for the current page."""
        data: dict[str, Any] = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        try:
            page_data = data["searchScope"]["projects"]
            self.last_response = ProjectConnectionFields.model_validate(page_data)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[Automation]:
        """Parse the page data into a list of objects."""
        page = self.last_response
        return AutomationListAdapter.validate_python(
            chain.from_iterable(edge.node.triggers for edge in page.edges)
        )


class AutomationsForViewer(Paginator[Automation]):
    QUERY: ClassVar[Document] = gql(GET_TRIGGERS_GQL)

    last_response: ProjectConnectionFields | None

    @property
    def more(self) -> bool:
        """Whether there are more items to fetch."""
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
        """Fetch the raw response data for the current page."""
        data: dict[str, Any] = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        try:
            page_data = data["searchScope"]["projects"]
            self.last_response = ProjectConnectionFields.model_validate(page_data)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[Automation]:
        """Parse the page data into a list of objects."""
        page = self.last_response
        return AutomationListAdapter.validate_python(
            chain.from_iterable(edge.node.triggers for edge in page.edges)
        )
