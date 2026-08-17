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
    from wandb.automations._generated import (
        GetAutomationsLegacy,
        GetEntityAutomationsLegacy,
        ProjectTriggersFields,
        TriggerFields,
    )


class _LegacyAutomationsPaginator(
    RelayPaginator["ProjectTriggersFields", "Automation"]
):
    """A lazy iterator of `Automation` objects for older servers.

    For older servers that don't support direct queries for automations, this
    walks projects for all automations that are visible to the user.
    Obviously, this is suboptimal.
    """

    QUERY: ClassVar[str | None] = None  # type: ignore[misc]
    last_response: Connection[ProjectTriggersFields] | None

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

    @classmethod
    def _response_cls(cls) -> type[GetAutomationsLegacy | GetEntityAutomationsLegacy]:
        """The generated type that parses the raw response for `QUERY`."""
        raise NotImplementedError

    @override
    def _update_response(self) -> None:
        """Fetch the raw response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import ProjectTriggersFields

        try:
            res = self._execute_query(parse=self._response_cls().model_validate_json)
            conn = Connection[ProjectTriggersFields].model_validate(res.scope.projects)  # type: ignore[attr-defined]
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e
        else:
            self.last_response = conn

    @override
    def _convert(self, node: ProjectTriggersFields) -> Iterator[Automation]:
        from wandb.automations import Automation

        # Project.triggers doesn't support filters, so we have to filter client-side.
        if name := self._name:
            return map(
                Automation.model_validate,
                filter(lambda t: t.name == name, node.triggers),
            )
        return map(Automation.model_validate, node.triggers)

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

    @classmethod
    @override
    def _response_cls(cls) -> type[GetAutomationsLegacy]:
        from wandb.automations._generated import GetAutomationsLegacy

        return GetAutomationsLegacy


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

    @classmethod
    @override
    def _response_cls(cls) -> type[GetEntityAutomationsLegacy]:
        from wandb.automations._generated import GetEntityAutomationsLegacy

        return GetEntityAutomationsLegacy


class EntityAutomations(RelayPaginator["TriggerFields", "Automation"]):
    """A lazy iterator of `Automation` objects from an entity."""

    QUERY: ClassVar[str | None] = None  # type: ignore[misc]
    last_response: Connection[TriggerFields] | None

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
        from wandb._pydantic import Connection
        from wandb.automations._generated import GetEntityAutomations, TriggerFields

        try:
            res = self._execute_query(parse=GetEntityAutomations.model_validate_json)
            conn = Connection[TriggerFields].model_validate(res.scope.triggers)  # type: ignore[union-attr]
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e
        else:
            self.last_response = conn

    @override
    def _convert(self, node: TriggerFields) -> Automation:
        from wandb.automations import Automation

        return Automation.model_validate(node)


Automations: TypeAlias = LegacyAutomations  # For now
