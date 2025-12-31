"""W&B Public API for Automation objects."""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Any, Iterator, Mapping

from pydantic import ValidationError
from typing_extensions import override

from wandb.apis.paginator import RelayPaginator

if TYPE_CHECKING:
    from wandb_graphql.language.ast import Document

    from wandb._pydantic import Connection
    from wandb.apis.public.api import RetryingClient
    from wandb.automations import Automation
    from wandb.automations._generated import ProjectTriggersFields


class Automations(RelayPaginator["ProjectTriggersFields", "Automation"]):
    """A lazy iterator of `Automation` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    QUERY: Document  # Must be set per-instance
    last_response: Connection[ProjectTriggersFields] | None

    def __init__(
        self,
        client: RetryingClient,
        variables: Mapping[str, Any],
        per_page: int = 50,
        *,
        _query: Document,  # internal use only, but required
    ):
        self.QUERY = _query
        super().__init__(client, variables=variables, per_page=per_page)

    @override
    def _update_response(self) -> None:
        """Fetch the raw response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import ProjectTriggersFields

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        try:
            conn_data = data["scope"]["projects"]
            conn = Connection[ProjectTriggersFields].model_validate(conn_data)
            self.last_response = conn
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    @override
    def _convert(self, node: ProjectTriggersFields) -> Iterator[Automation]:
        from wandb.automations import Automation

        return (Automation.model_validate(obj) for obj in node.triggers)

    @override
    def convert_objects(self) -> Iterator[Automation]:
        return chain.from_iterable(super().convert_objects())
