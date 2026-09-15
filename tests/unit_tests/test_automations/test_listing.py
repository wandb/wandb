import copy
import json
from unittest.mock import Mock

from pydantic import ValidationError
from pytest import fixture, mark, raises
from wandb.apis.public.automations import (
    EntityAutomations,
    LegacyAutomations,
    LegacyEntityAutomations,
)


@fixture
def node():
    return {
        "__typename": "Trigger",
        "id": "VHJpZ2dlcjox",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": None,
        "name": "wanted",
        "description": None,
        "enabled": True,
        "scope": {"__typename": "Project", "id": "UHJvamVjdDox", "name": "project"},
        "event": {
            "__typename": "FilterEventTriggeringCondition",
            "eventType": "CREATE_ARTIFACT",
            "filter": json.dumps({"filter": {"$or": [{"$and": []}]}}),
        },
        "action": {"__typename": "NoOpTriggeredAction", "noOp": True},
    }


@fixture(params=[EntityAutomations, LegacyAutomations, LegacyEntityAutomations])
def listing(request):
    cls = request.param

    def make(pages, **kwargs):
        api = Mock()
        api.feature_enabled.return_value = True
        api.requested_cursors = []
        remaining = iter(enumerate(pages))

        def execute(query, *, parse, variables, **options):
            api.requested_cursors.append(variables["cursor"])
            index, nodes = next(remaining)
            connection = {
                "pageInfo": {
                    "endCursor": f"cursor-{index}",
                    "hasNextPage": index < len(pages) - 1,
                },
                "edges": [{"node": node} for node in nodes],
            }
            if cls is EntityAutomations:
                data = {"scope": {"triggers": connection}}
            else:
                connection["edges"] = [
                    {"node": {"__typename": "Project", "triggers": nodes}}
                ]
                data = {"scope": {"projects": connection}}
            return parse(json.dumps(data))

        api.execute_graphql.side_effect = execute
        args = () if cls is LegacyAutomations else ("entity",)
        return cls(api, *args, **kwargs), api

    return make


@mark.parametrize(
    ("field", "payload"),
    [
        ("action", {"__typename": "FutureTriggeredAction"}),
        ("action", {"__typename": "PushNotificationTriggeredAction"}),
        ("event", {"__typename": "FutureTriggeringCondition"}),
        (
            "event",
            {
                "__typename": "FilterEventTriggeringCondition",
                "eventType": "FUTURE_EVENT",
            },
        ),
        ("scope", {"__typename": "FutureScope"}),
    ],
)
def test_listing_skips_unsupported_types(listing, node, field, payload):
    unknown = copy.deepcopy(node)
    unknown[field] = payload
    paginator, _ = listing([[unknown, node, unknown]])
    rows = list(paginator)
    assert [row.id for row in rows] == [node["id"]]
    assert rows[0].scope.name == "project"


@mark.parametrize("supported_last", [False, True])
def test_listing_continues_through_unsupported_pages(listing, node, supported_last):
    unknown = dict(node, action={"__typename": "FutureTriggeredAction"})
    pages = [[unknown], [], [unknown], [node] if supported_last else [unknown]]
    paginator, api = listing(pages, start="resume", per_page=1)
    rows = list(paginator)
    assert len(rows) == int(supported_last)
    assert api.requested_cursors == ["resume", "cursor-0", "cursor-1", "cursor-2"]
    assert paginator.cursor == "cursor-3"
    assert not paginator.more


def test_listing_resumes_after_supported_and_empty_pages(listing, node):
    unknown = dict(node, action={"__typename": "FutureTriggeredAction"})
    paginator, api = listing([[node], [unknown], [node], [unknown]])
    assert next(paginator).id == node["id"]
    assert api.execute_graphql.call_count == 1
    assert next(paginator).id == node["id"]
    assert api.execute_graphql.call_count == 3
    with raises(StopIteration):
        next(paginator)
    assert api.execute_graphql.call_count == 4


def test_listing_index_fetches_past_unsupported_page(listing, node):
    unknown = dict(node, scope={"__typename": "FutureScope"})
    paginator, api = listing([[unknown], [node]])
    assert paginator[0].id == node["id"]
    assert api.execute_graphql.call_count == 2


@mark.parametrize("malformed", [{}, {"__typename": "ARIATriggeredAction"}, None])
def test_listing_does_not_hide_malformed_supported_data(listing, node, malformed):
    node["action"] = malformed
    paginator, _ = listing([[node]])
    with raises(ValueError, match="Unexpected response data"):
        list(paginator)


def test_listing_validates_supported_event_filter(listing, node):
    node["event"]["filter"] = "invalid JSON"
    paginator, _ = listing([[node]])
    with raises(ValidationError):
        list(paginator)


@mark.parametrize("cls", [LegacyAutomations, LegacyEntityAutomations])
def test_legacy_name_filter_precedes_public_validation(node, cls):
    other = copy.deepcopy(node)
    other["name"] = "other"
    other["event"]["filter"] = "invalid JSON"
    api = Mock()
    api.feature_enabled.return_value = True
    pages = iter([[other], [other, node]])

    def execute(query, *, parse, variables, **kwargs):
        nodes = next(pages)
        return parse(
            json.dumps(
                {
                    "scope": {
                        "projects": {
                            "pageInfo": {
                                "endCursor": "next",
                                "hasNextPage": len(nodes) == 1,
                            },
                            "edges": [
                                {"node": {"__typename": "Project", "triggers": nodes}}
                            ],
                        }
                    }
                }
            )
        )

    api.execute_graphql.side_effect = execute
    args = () if cls is LegacyAutomations else ("entity",)
    rows = list(cls(api, *args, name="wanted"))
    assert [row.name for row in rows] == ["wanted"]
    assert api.execute_graphql.call_count == 2
