"""W&B Public API for Automation objects."""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from pydantic import ValidationError
from typing_extensions import override
from wandb_graphql.language.ast import Document

from wandb.apis.paginator import Paginator, _Client

if TYPE_CHECKING:
    from wandb._pydantic import Connection
    from wandb.automations import Automation
    from wandb.automations._generated import ProjectTriggersFields


class Automations(Paginator["Automation"]):
    """An lazy iterator of `Automation` objects.

    <!-- lazydoc-ignore-init: internal -->
    """

    last_response: Connection[ProjectTriggersFields] | None
    _query: Document

    def __init__(
        self,
        client: _Client,
        variables: Mapping[str, Any],
        per_page: int = 50,
        *,
        _query: Document,  # internal use only, but required
    ):
        super().__init__(client, variables=variables, per_page=per_page)
        self._query = _query

    @property
    def more(self) -> bool:
        """Whether there are more items to fetch.

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
        """Fetch the raw response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import ProjectTriggersFields

        data = self.client.execute(self._query, variable_values=self.variables)
        try:
            conn_data = data["scope"]["projects"]
            conn = Connection[ProjectTriggersFields].model_validate(conn_data)
            self.last_response = conn
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> Iterable[Automation]:
        """Parse the page data into a list of objects.

        <!-- lazydoc-ignore: internal -->
        """
        from wandb.automations import Automation

        if (conn := self.last_response) is None:
            return []
        return [
            Automation.model_validate(obj)
            for obj in chain.from_iterable(node.triggers for node in conn.nodes())
        ]
