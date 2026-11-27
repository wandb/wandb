"""W&B Public API for Automation objects."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias

from pydantic import ValidationError
from typing_extensions import override

import wandb
from wandb._pydantic import GQLResult
from wandb.apis.paginator import RelayPaginator

if TYPE_CHECKING:
    from wandb._pydantic import Connection
    from wandb.apis.public.service_api import ServiceApi
    from wandb.automations import Automation

logger = logging.getLogger(__name__)

_RawTrigger: TypeAlias = dict[str, Any]
"""An unparsed `TriggerFields` node from the GraphQL response."""


class _RawProjectTriggers(GQLResult):
    """A project node whose triggers are left unparsed."""

    triggers: list[_RawTrigger]


def _parse_automation(node: _RawTrigger, *, skip: bool) -> Automation | None:
    """Parse a single trigger node, or return None if this SDK can't parse it.

    Servers can return automations with scopes, events, or actions that this
    version of the SDK doesn't know about, e.g. a newly added action type, or a
    type whose GraphQL fragment was omitted because the server doesn't advertise
    the matching feature flag. Skip those instead of failing the whole listing.

    If `skip` is False, raise a `ValueError` instead. Lookups by name must not
    skip: names are only unique within a scope, so skipping one match could
    make the lookup silently return another automation with the same name, or
    report that no automation exists.
    """
    from wandb.automations import Automation
    from wandb.automations._generated import TriggerFields

    try:
        return Automation.model_validate(TriggerFields.model_validate(node))
    except ValidationError as e:
        if not skip:
            msg = (
                f"Automation {node.get('name')!r} can't be parsed by this version"
                " of wandb. Upgrade wandb to fetch it."
            )
            raise ValueError(msg) from e
        logger.debug(
            "Skipping automation %r (id=%r) that could not be parsed: %s",
            node.get("name"),
            node.get("id"),
            e,
        )
        wandb.termwarn(
            "Skipping one or more automations that this version of wandb"
            " doesn't support. Upgrade wandb to list them.",
            repeat=False,
        )
        return None


class _SkipEmptyPagesMixin:
    """Keep fetching past pages that produce no objects.

    `Paginator.__next__()` stops iterating if a freshly loaded page adds no
    objects, even if the server reports more pages. Automation pages can be
    empty after conversion, e.g. if every automation on the page was skipped
    as unparseable or filtered out by name, so keep loading until a page adds
    an object or there are no more pages.
    """

    objects: list[Automation]
    more: bool

    def _load_page(self) -> bool:
        count = len(self.objects)
        loaded = super()._load_page()  # type: ignore[misc]
        while loaded and len(self.objects) == count and self.more:
            loaded = super()._load_page()  # type: ignore[misc]
        return loaded


class _LegacyAutomationsPaginator(
    _SkipEmptyPagesMixin, RelayPaginator[_RawProjectTriggers, "Automation"]
):
    """A lazy iterator of `Automation` objects for older servers.

    For older servers that don't support direct queries for automations, this
    walks projects for all automations that are visible to the user.
    Obviously, this is suboptimal.
    """

    QUERY: ClassVar[str | None] = None  # type: ignore[misc]
    last_response: Connection[_RawProjectTriggers] | None

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
        from wandb._pydantic import Connection

        # Leave the individual trigger nodes unparsed here, so that one
        # automation we can't parse doesn't fail the whole page.
        try:
            res = self._execute_query()
            projects = res["scope"]["projects"]
            conn = Connection[_RawProjectTriggers].model_validate(projects)
        except (LookupError, TypeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e
        else:
            self.last_response = conn

    @override
    def _convert(self, node: _RawProjectTriggers) -> Iterator[Automation]:
        triggers = node.triggers
        # Project.triggers doesn't support filters, so we have to filter client-side.
        if name := self._name:
            triggers = [t for t in triggers if t.get("name") == name]
        # Don't skip unparseable automations when looking one up by name.
        skip = not self._name
        return filter(None, (_parse_automation(t, skip=skip) for t in triggers))

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


class EntityAutomations(
    _SkipEmptyPagesMixin, RelayPaginator[_RawTrigger, "Automation"]
):
    """A lazy iterator of `Automation` objects from an entity."""

    QUERY: ClassVar[str | None] = None  # type: ignore[misc]
    last_response: Connection[_RawTrigger] | None

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

        # Only skip unparseable automations when listing without a filter, e.g.
        # not when looking one up by name (see `_parse_automation`).
        self._skip_unparseable = not filter

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

        # Leave the individual trigger nodes unparsed here, so that one
        # automation we can't parse doesn't fail the whole page.
        try:
            res = self._execute_query()
            triggers = res["scope"]["triggers"]
            conn = Connection[_RawTrigger].model_validate(triggers)
        except (LookupError, TypeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e
        else:
            self.last_response = conn

    @override
    def _convert(self, node: _RawTrigger) -> Automation | None:
        return _parse_automation(node, skip=self._skip_unparseable)


Automations: TypeAlias = LegacyAutomations  # For now
