"""W&B Public API for Automation objects."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Any, ClassVar

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
    )


class _LegacyAutomationsPaginator(
    RelayPaginator["ProjectTriggersFields", "Automation"]
):
    """A lazy iterator of automations found by walking projects."""

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
        omit_variables: Iterable[str] | None = None,
        omit_fragments: Iterable[str] | None = None,
        omit_fields: Iterable[str] | None = None,
        rename_fields: Mapping[str, str] | None = None,
    ):
        self._name = name
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


class Automations(_LegacyAutomationsPaginator):
    """A generic legacy automations paginator retained for compatibility."""

    QUERY: str  # type: ignore[misc]

    def __init__(
        self,
        service_api: ServiceApi,
        variables: Mapping[str, Any],
        per_page: int = 50,
        *,
        start: str | None = None,
        _query: str,
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
        """Fetch raw response data for the compatibility query."""
        from wandb._pydantic import Connection
        from wandb.automations._generated import ProjectTriggersFields

        data: dict[str, Any] = self._execute_query()
        try:
            conn = Connection[ProjectTriggersFields].model_validate(
                data["scope"]["projects"]
            )
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e
        else:
            self.last_response = conn


class LegacyAutomations(_LegacyAutomationsPaginator):
    """A lazy iterator of automations found by walking the viewer's projects."""

    def __init__(
        self,
        service_api: ServiceApi,
        *,
        name: str | None = None,
        per_page: int = 50,
        start: str | None = None,
        omit_fragments: Iterable[str] | None = None,
    ):
        if self.QUERY is None:
            from wandb.automations._generated import GET_AUTOMATIONS_LEGACY_GQL

            type(self).QUERY = GET_AUTOMATIONS_LEGACY_GQL

        super().__init__(
            service_api,
            variables={},
            name=name,
            per_page=per_page,
            start=start,
            omit_fragments=omit_fragments,
        )

    @classmethod
    @override
    def _response_cls(cls) -> type[GetAutomationsLegacy]:
        from wandb.automations._generated import GetAutomationsLegacy

        return GetAutomationsLegacy


class LegacyEntityAutomations(_LegacyAutomationsPaginator):
    """A lazy iterator of an entity's automations found by walking its projects."""

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        *,
        name: str | None = None,
        per_page: int = 50,
        start: str | None = None,
        omit_fragments: Iterable[str] | None = None,
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
            omit_fragments=omit_fragments,
        )

    @classmethod
    @override
    def _response_cls(cls) -> type[GetEntityAutomationsLegacy]:
        from wandb.automations._generated import GetEntityAutomationsLegacy

        return GetEntityAutomationsLegacy
