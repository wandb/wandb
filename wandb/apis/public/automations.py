"""W&B Public API for Automation objects."""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from pydantic import ValidationError
from typing_extensions import override
from wandb_graphql.language.ast import Document

from wandb._strutils import nameof
from wandb.apis.paginator import Paginator, _Client

if TYPE_CHECKING:
    from wandb.automations import Automation
    from wandb.automations._generated import ProjectConnectionFields


class Automations(Paginator["Automation"]):
    """An lazy iterator of `Automation` objects.

    <!-- lazydoc-ignore-init: internal -->
    """

    last_response: ProjectConnectionFields | None
    _query: Document

    def __init__(
        self,
        client: _Client,
        variables: Mapping[str, Any],
        per_page: int = 50,
        _query: Document | None = None,
    ):
        super().__init__(client, variables, per_page=per_page)
        if _query is None:
            raise RuntimeError(f"Query required for {nameof(type(self))}")
        self._query = _query

    @property
    def more(self) -> bool:
        """Whether there are more items to fetch.

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
        """Fetch the raw response data for the current page."""
        from wandb.automations._generated import ProjectConnectionFields

        data: dict[str, Any] = self.client.execute(
            self._query, variable_values=self.variables
        )
        try:
            page_data = data["searchScope"]["projects"]
            self.last_response = ProjectConnectionFields.model_validate(page_data)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[Automation]:
        """Parse the page data into a list of objects.

        <!-- lazydoc-ignore: internal -->
        """
        from wandb.automations import Automation

        page = self.last_response
        return [
            Automation.model_validate(obj)
            for obj in chain.from_iterable(edge.node.triggers for edge in page.edges)
        ]
