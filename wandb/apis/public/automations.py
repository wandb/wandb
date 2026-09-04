"""W&B Public API for Automation objects."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias

from pydantic import ValidationError
from typing_extensions import override

from wandb.apis.paginator import RelayPaginator

if TYPE_CHECKING:
    from wandb._pydantic import Connection
    from wandb.apis.public.service_api import ServiceApi
    from wandb.automations import Automation
    from wandb.automations.automations import ProjectAutomations


class _LegacyAutomationsPaginator(RelayPaginator["ProjectAutomations", "Automation"]):
    """A lazy iterator of `Automation` objects for older servers.

    For older servers that don't support direct queries for automations, this
    walks projects for all automations that are visible to the user.
    Obviously, this is suboptimal.
    """

    QUERY: ClassVar[str | None] = None  # type: ignore[misc]
    last_response: Connection[ProjectAutomations] | None

    def __init__(
        self,
        service_api: ServiceApi,
        variables: Mapping[str, Any],
        *,
        name: str | None = None,
        per_page: int = 50,
        start: str | None = None,
    ):
        from wandb.automations._compat import omit_automation_fragments

        self._name = name

        super().__init__(
            service_api,
            variables=variables,
            per_page=per_page,
            start=start,
            omit_fragments=omit_automation_fragments(service_api),
        )

    @override
    def _update_response(self) -> None:
        """Fetch the raw response data for the current page."""
        from wandb.automations.automations import LegacyAutomationsPage

        try:
            res = self._execute_query(parse=LegacyAutomationsPage.model_validate_json)
            conn = res.scope.projects  # type: ignore[union-attr]
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

        if conn is None:
            raise ValueError("Unexpected response data: missing projects connection")
        self.last_response = conn

    @override
    def _convert(self, node: ProjectAutomations) -> Iterator[Automation]:
        # Project.triggers doesn't support filters, so we have to filter client-side.
        if name := self._name:
            return (t for t in node.triggers if t.name == name)
        return iter(node.triggers)

    @override
    def convert_objects(self) -> Iterator[Automation]:
        if conn := self.last_response:
            for node in conn.nodes():
                yield from self._convert(node)


class LegacyAutomations(_LegacyAutomationsPaginator):
    """A lazy iterator of `Automation` objects, walking the viewer's projects."""

    def __init__(
        self,
        service_api: ServiceApi,
        *,
        name: str | None = None,
        per_page: int = 50,
        start: str | None = None,
    ):
        if self.QUERY is None:
            from wandb.automations._generated import GET_AUTOMATIONS_LEGACY_GQL

            type(self).QUERY = GET_AUTOMATIONS_LEGACY_GQL

        super().__init__(
            service_api, variables={}, name=name, per_page=per_page, start=start
        )


class LegacyEntityAutomations(_LegacyAutomationsPaginator):
    """A lazy iterator of an entity's `Automation` objects, walking its projects."""

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        *,
        name: str | None = None,
        per_page: int = 50,
        start: str | None = None,
    ):
        if self.QUERY is None:
            from wandb.automations._generated import GET_ENTITY_AUTOMATIONS_LEGACY_GQL

            type(self).QUERY = GET_ENTITY_AUTOMATIONS_LEGACY_GQL

        super().__init__(
            service_api,
            variables={"entity": entity},
            name=name,
            per_page=per_page,
            start=start,
        )


class EntityAutomations(RelayPaginator["Automation", "Automation"]):
    """A lazy iterator of `Automation` objects from an entity."""

    QUERY: ClassVar[str | None] = None  # type: ignore[misc]
    last_response: Connection[Automation] | None

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        *,
        filter: dict[str, Any] | None = None,
        per_page: int = 50,
        start: str | None = None,
    ):
        from wandb._pydantic import to_json
        from wandb.automations._compat import omit_automation_fragments

        if self.QUERY is None:
            from wandb.automations._generated import GET_ENTITY_AUTOMATIONS_GQL

            type(self).QUERY = GET_ENTITY_AUTOMATIONS_GQL

        super().__init__(
            service_api,
            variables={
                "entity": entity,
                "filters": to_json(f) if (f := filter) else None,
            },
            per_page=per_page,
            start=start,
            omit_fragments=omit_automation_fragments(service_api),
        )

    @override
    def _update_response(self) -> None:
        """Fetch the raw response data for the current page."""
        from wandb.automations.automations import EntityAutomationsPage

        try:
            res = self._execute_query(parse=EntityAutomationsPage.model_validate_json)
            conn = res.scope.triggers  # type: ignore[union-attr]
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e
        else:
            self.last_response = conn

    @override
    def _convert(self, node: Automation) -> Automation:
        return node


Automations: TypeAlias = LegacyAutomations  # For now
