"""Tests for listing automations when some can't be parsed by this SDK version."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from pytest import fixture, mark, raises
from wandb.apis.public import automations as automations_module
from wandb.apis.public.automations import EntityAutomations, LegacyEntityAutomations


def _trigger(
    name: str,
    *,
    event_type: str = "CREATE_ARTIFACT",
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "__typename": "Trigger",
        "id": f"id-{name}",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": None,
        "name": name,
        "description": None,
        "enabled": True,
        "scope": {
            "__typename": "Project",
            "id": "UHJvamVjdDox",
            "name": "my-project",
        },
        "event": {
            "__typename": "FilterEventTriggeringCondition",
            "eventType": event_type,
            "filter": json.dumps({"filter": {"$or": [{"$and": []}]}}),
        },
        "action": action
        if action is not None
        else {"__typename": "NoOpTriggeredAction", "noOp": True},
    }


def _connection(
    nodes: list[Any], *, end_cursor: str | None = None, has_next: bool = False
) -> dict[str, Any]:
    return {
        "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next},
        "edges": [{"node": node} for node in nodes],
    }


# A page mixing automations this SDK can and can't parse.
MIXED_TRIGGERS = [
    _trigger("supported"),
    # An action type this SDK has no fragment for: the server selects no fields.
    _trigger("unknown-action", action={}),
    # An event type this SDK doesn't know about.
    _trigger("unknown-event", event_type="SOME_FUTURE_EVENT"),
    _trigger("also-supported"),
]


@fixture
def termwarn(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(automations_module.wandb, "termwarn", mock)
    return mock


def _service_api(*responses: dict[str, Any]) -> MagicMock:
    """A fake `ServiceApi` that returns each response in turn.

    Like the real `execute_graphql`, it hands the serialized response to the
    `parse` callable it was given, so the tests exercise however the paginator
    chooses to parse each page.
    """
    pages = iter(responses)

    def execute_graphql(*_: Any, parse=json.loads, **__: Any) -> Any:
        return parse(json.dumps(next(pages)))

    service_api = MagicMock()
    service_api.execute_graphql.side_effect = execute_graphql
    return service_api


def _assert_warned_once_per_process(termwarn: MagicMock) -> None:
    """The skip warning was emitted, deduplicated via `repeat=False`."""
    termwarn.assert_called()
    for call in termwarn.call_args_list:
        assert "Upgrade wandb" in call.args[0]
        assert call.kwargs.get("repeat") is False


def test_entity_automations_skips_unparseable(termwarn):
    response = {"scope": {"triggers": _connection(MIXED_TRIGGERS)}}

    automations = list(EntityAutomations(_service_api(response), entity="my-entity"))

    assert [a.name for a in automations] == ["supported", "also-supported"]
    _assert_warned_once_per_process(termwarn)


def test_entity_automations_no_warning_when_all_parse(termwarn):
    triggers = [_trigger("a"), _trigger("b")]
    response = {"scope": {"triggers": _connection(triggers)}}

    automations = list(EntityAutomations(_service_api(response), entity="my-entity"))

    assert [a.name for a in automations] == ["a", "b"]
    termwarn.assert_not_called()


def test_legacy_entity_automations_filters_by_name_before_parsing(termwarn):
    project = {"__typename": "Project", "triggers": MIXED_TRIGGERS}
    response = {"scope": {"projects": _connection([project])}}

    automations = list(
        LegacyEntityAutomations(
            _service_api(response), entity="my-entity", name="also-supported"
        )
    )

    assert [a.name for a in automations] == ["also-supported"]
    # The unparseable automations were filtered out by name, so no warning.
    termwarn.assert_not_called()


UNPARSEABLE_TRIGGER = _trigger("unknown-action", action={})


def _entity_page(triggers: list[Any], **page_info: Any) -> dict[str, Any]:
    return {"scope": {"triggers": _connection(triggers, **page_info)}}


def _legacy_page(triggers: list[Any], **page_info: Any) -> dict[str, Any]:
    project = {"__typename": "Project", "triggers": triggers}
    return {"scope": {"projects": _connection([project], **page_info)}}


PAGINATORS = mark.parametrize(
    ("paginator_cls", "page"),
    [
        (EntityAutomations, _entity_page),
        (LegacyEntityAutomations, _legacy_page),
    ],
    ids=["entity", "legacy"],
)


@PAGINATORS
def test_continues_past_consecutive_fully_skipped_pages(termwarn, paginator_cls, page):
    service_api = _service_api(
        page([UNPARSEABLE_TRIGGER], end_cursor="c1", has_next=True),
        page([UNPARSEABLE_TRIGGER], end_cursor="c2", has_next=True),
        page([_trigger("on-page-3")]),
    )

    automations = list(paginator_cls(service_api, entity="my-entity"))

    assert [a.name for a in automations] == ["on-page-3"]
    assert service_api.execute_graphql.call_count == 3


@PAGINATORS
def test_continues_past_fully_skipped_page_after_a_listed_one(
    termwarn, paginator_cls, page
):
    service_api = _service_api(
        page([_trigger("on-page-1")], end_cursor="c1", has_next=True),
        page([UNPARSEABLE_TRIGGER], end_cursor="c2", has_next=True),
        page([_trigger("on-page-3")]),
    )

    automations = list(paginator_cls(service_api, entity="my-entity"))

    assert [a.name for a in automations] == ["on-page-1", "on-page-3"]
    assert service_api.execute_graphql.call_count == 3


@PAGINATORS
def test_stops_after_last_fully_skipped_page(termwarn, paginator_cls, page):
    service_api = _service_api(page([UNPARSEABLE_TRIGGER]))

    assert list(paginator_cls(service_api, entity="my-entity")) == []
    assert service_api.execute_graphql.call_count == 1


def test_legacy_entity_automations_continues_past_pages_without_name_match():
    service_api = _service_api(
        _legacy_page([_trigger("other")], end_cursor="c1", has_next=True),
        _legacy_page([_trigger("wanted")]),
    )

    automations = list(
        LegacyEntityAutomations(service_api, entity="my-entity", name="wanted")
    )

    assert [a.name for a in automations] == ["wanted"]


@mark.parametrize(
    ("paginator_cls", "page", "lookup"),
    [
        (EntityAutomations, _entity_page, {"filter": {"name": "dupe"}}),
        (LegacyEntityAutomations, _legacy_page, {"name": "dupe"}),
    ],
    ids=["entity", "legacy"],
)
def test_lookup_by_name_raises_on_unparseable(paginator_cls, page, lookup):
    # Names are only unique within a scope, so a name lookup can match both an
    # automation we can parse and one we can't. Skipping the latter would make
    # `Api.automation()` silently return the wrong one.
    response = page([_trigger("dupe"), _trigger("dupe", action={})])
    paginator = paginator_cls(_service_api(response), entity="my-entity", **lookup)

    with raises(ValueError, match="'dupe' can't be parsed"):
        list(paginator)
