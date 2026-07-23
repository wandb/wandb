"""W&B Public API for Automation objects."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias

from pydantic import ValidationError
from typing_extensions import override

from wandb.apis.paginator import RelayPaginator

if TYPE_CHECKING:
    from wandb._pydantic import Connection
    from wandb.apis.public.service_api import ServiceApi
    from wandb.automations import Automation
    from wandb.automations._generated import ProjectTriggersFields, TriggerFields


class LegacyAutomations(RelayPaginator["ProjectTriggersFields", "Automation"]):
    """A lazy iterator of `Automation` objects.

    For older servers that don't support direct queries for automations, this
    walks the viewer's projects for all automations that are visible to them.
    Obviously, this is suboptimal.
    """

    QUERY: ClassVar[str | None] = None  # type: ignore[misc]
    last_response: Connection[ProjectTriggersFields] | None

    def __init__(
        self,
        service_api: ServiceApi,
        *,
        name: str | None = None,
        per_page: int = 50,
        start: str | None = None,
    ):
        from wandb.automations._utils import omit_automation_fragments

        if self.QUERY is None:
            from wandb.automations._generated import GET_AUTOMATIONS_LEGACY_GQL

            type(self).QUERY = GET_AUTOMATIONS_LEGACY_GQL

        self._name = name

        super().__init__(
            service_api,
            variables={},
            per_page=per_page,
            start=start,
            omit_fragments=omit_automation_fragments(service_api),
        )

    @override
    def _update_response(self) -> None:
        """Fetch the raw response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import (
            GetAutomationsLegacy,
            ProjectTriggersFields,
        )

        try:
            res = self._execute_query(parse=GetAutomationsLegacy.model_validate_json)
            conn = Connection[ProjectTriggersFields].model_validate(res.scope.projects)  # type: ignore[union-attr]
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


class LegacyEntityAutomations(RelayPaginator["ProjectTriggersFields", "Automation"]):
    """A lazy iterator of `Automation` objects scoped directly to an entity.

    For older servers that don't support direct queries for entity-scoped automations,
    this walks an entity's projects for all automations that are visible to the user.
    Obviously, this is suboptimal.
    """

    QUERY: ClassVar[str | None] = None  # type: ignore[misc]
    last_response: Connection[ProjectTriggersFields] | None

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        *,
        name: str | None = None,
        per_page: int = 50,
        start: str | None = None,
    ):
        from wandb.automations._utils import omit_automation_fragments

        if self.QUERY is None:
            from wandb.automations._generated import GET_ENTITY_AUTOMATIONS_LEGACY_GQL

            type(self).QUERY = GET_ENTITY_AUTOMATIONS_LEGACY_GQL

        self._name = name

        super().__init__(
            service_api,
            variables={"entity": entity},
            per_page=per_page,
            start=start,
            omit_fragments=omit_automation_fragments(service_api),
        )

    @override
    def _update_response(self) -> None:
        """Fetch the raw response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import (
            GetEntityAutomationsLegacy,
            ProjectTriggersFields,
        )

        try:
            res = self._execute_query(
                parse=GetEntityAutomationsLegacy.model_validate_json
            )
            conn = Connection[ProjectTriggersFields].model_validate(res.scope.projects)  # type: ignore[union-attr]
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
        from wandb.automations._utils import omit_automation_fragments

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
