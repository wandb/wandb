"""W&B Public API for Automation objects."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from typing_extensions import override

from wandb.apis.paginator import RelayPaginator

if TYPE_CHECKING:
    from wandb._pydantic import Connection
    from wandb.apis.public.service_api import ServiceApi
    from wandb.automations import Automation
    from wandb.automations._generated import ProjectTriggersFields


class Automations(RelayPaginator["ProjectTriggersFields", "Automation"]):
    """A lazy iterator of `Automation` objects.

    <!-- lazydoc-ignore-class: internal -->
    """

    QUERY: str  # Must be set per-instance
    last_response: Connection[ProjectTriggersFields] | None

    def __init__(
        self,
        service_api: ServiceApi,
        variables: Mapping[str, Any],
        per_page: int = 50,
        *,
        start: str | None = None,
        _query: str,  # internal use only, but required
        omit_variables: Iterable[str] | None = None,
        omit_fragments: Iterable[str] | None = None,
        omit_fields: Iterable[str] | None = None,
        rename_fields: Mapping[str, str] | None = None,
    ):
        self.QUERY = _query
        super().__init__(
            service_api,
            variables=variables,
            per_page=per_page,
            start=start,
            omit_variables=omit_variables,
            omit_fragments=omit_fragments,
            omit_fields=omit_fields,
            rename_fields=rename_fields,
        )

    @override
    def _update_response(self) -> None:
        """Fetch the raw response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import ProjectTriggersFields

        data: dict[str, Any] = self._execute_query()
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
        if conn := self.last_response:
            for node in conn.nodes():
                yield from self._convert(node)
