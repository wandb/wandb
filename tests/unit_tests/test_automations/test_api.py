"""Public API contracts for saved-rule updates and missing-rule recovery."""

from __future__ import annotations

import json
from copy import deepcopy

from pytest import fixture, mark, raises
from wandb.apis.public import Api
from wandb.automations import (
    Automation,
    DoNothing,
    OnLinkArtifact,
    OnRunMetric,
    OnRunState,
    RunEvent,
)
from wandb.errors import CommError
from wandb.proto.wandb_api_pb2 import ApiErrorResponse
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

from ._helpers import _service_api, _trigger


@fixture
def api():
    # These methods depend only on _service_api, supplied by each test. Avoid
    # constructing a real service or authenticating to a backend.
    return object.__new__(Api)


def _error(status):
    return WandbApiFailedError("request failed", ApiErrorResponse(http_status=status))


def _saved(event):
    node = _trigger("rule")
    node["scope"] = event.scope.model_dump()
    node["enabled"] = False
    node["description"] = "saved description"
    node["event"] = {
        "__typename": "FilterEventTriggeringCondition",
        "eventType": event.event_type,
        "filter": json.dumps({"filter": event.filter.model_dump()})
        if event.event_type == "LINK_MODEL"
        else event.filter.model_dump_json(),
    }
    node["action"] = {
        "__typename": "GenericWebhookTriggeredAction",
        "integration": {
            "__typename": "GenericWebhookIntegration",
            "id": "integration",
            "name": "test integration",
            "urlEndpoint": "https://example.com/webhook",
        },
        "requestPayload": json.dumps({"nested": {"value": 1}}),
    }
    return node


@mark.parametrize("case", ["artifact", "metric", "state", "overrides"])
def test_missing_update_recreates_the_resolved_rule(api, project, case):
    events = {
        "artifact": OnLinkArtifact(scope=project),
        "metric": OnRunMetric(
            scope=project, filter=RunEvent.metric("loss").avg(5).gt(2)
        ),
        "state": OnRunState(scope=project, filter=RunEvent.state == "failed"),
    }
    node = _saved(events.get(case, events["artifact"]))
    saved = Automation.model_validate(node)
    overrides = {}
    expected = deepcopy(node)
    if case == "overrides":
        overrides = {
            "name": "replacement",
            "description": "new description",
            "enabled": True,
            "event": events["state"],
            "action": DoNothing(),
        }
        expected.update(
            name="replacement",
            description="new description",
            enabled=True,
            event={
                "__typename": "FilterEventTriggeringCondition",
                "eventType": "RUN_STATE",
                "filter": events["state"].filter.model_dump_json(),
            },
            action={"__typename": "NoOpTriggeredAction", "noOp": True},
        )
    expected["id"] = "new-rule-id"
    api._service_api = service = _service_api(
        _error(404), {"result": {"trigger": expected}}
    )

    recreated = api.update_automation(saved, create_missing=True, **overrides)

    assert recreated == Automation.model_validate(expected)
    calls = service.execute_graphql.call_args_list
    assert len(calls) == 2
    assert "mutation CreateAutomation" in calls[1].args[0]
    update_input = calls[0].kwargs["variables"]["input"]
    create_input = calls[1].kwargs["variables"]["input"]
    assert create_input == {k: v for k, v in update_input.items() if k != "id"}
    assert saved.id == node["id"]
    assert saved.enabled is False


@mark.parametrize(
    ("status", "recover"),
    [(404, False), (403, True)],
    ids=["missing-without-recovery", "forbidden-with-recovery"],
)
def test_update_errors_do_not_create(api, project, status, recover):
    saved = Automation.model_validate(_saved(OnLinkArtifact(scope=project)))
    api._service_api = service = _service_api(_error(status))
    with raises(CommError):
        api.update_automation(saved, create_missing=recover)
    assert service.execute_graphql.call_count == 1


def test_existing_rule_is_updated_without_create(api, project):
    node = _saved(OnLinkArtifact(scope=project))
    saved = Automation.model_validate(node)
    expected = node | {"enabled": True}
    api._service_api = service = _service_api({"result": {"trigger": expected}})

    updated = api.update_automation(saved, enabled=True)

    assert updated == Automation.model_validate(expected)
    service.execute_graphql.assert_called_once()
    assert "mutation UpdateAutomation" in service.execute_graphql.call_args.args[0]
    assert (
        service.execute_graphql.call_args.kwargs["variables"]["input"]["enabled"]
        is True
    )
