import json
from unittest.mock import Mock

import pytest
from wandb.apis.public.sweeps import (
    Agent,
    Sweep,
    _agent_heartbeat,
    _sweep_with_runs,
    _upsert_sweep,
)
from wandb.errors import CommError, UnsupportedError
from wandb.proto import wandb_api_pb2 as apb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps import SweepNotFoundError


def _make_sweep(
    mocker, *, feature_enabled: bool = True, graphql_response=None
) -> Sweep:
    """Build a Sweep backed by a mocked service API.

    Passing ``attrs`` keeps the constructor from issuing a load() query.
    """
    service_api = mocker.MagicMock()
    service_api.feature_enabled.return_value = feature_enabled
    if graphql_response is not None:
        service_api.execute_graphql.return_value = graphql_response
    sweep = Sweep(
        service_api=service_api,
        entity="entity",
        project="project",
        sweep_id="sweep-name",
        attrs={
            "id": "sweep-node-id",
            "name": "sweep-name",
            "config": "method: grid\n",
        },
    )
    return sweep


def test_enqueue_run_sends_correct_mutation(mocker):
    """enqueue_run issues the enqueueSweepRun mutation and returns the run id."""
    sweep = _make_sweep(
        mocker,
        feature_enabled=True,
        graphql_response={
            "enqueueSweepRun": {"id": "run-node-id", "runQueueItemId": "rqi-1"}
        },
    )

    config = {
        "learning_rate": {"value": 0.1},
        "batch_size": {"value": 32},
        "model": {"value": {"lr": 0.5, "layers": 4}},
    }
    run_id = sweep.enqueue_run(config, display_name="my-run")

    assert run_id == "run-node-id"

    sweep._service_api.feature_enabled.assert_called_once_with(
        pb.ServerFeature.SWEEPS_LOCAL_SCHEDULER
    )
    sweep._service_api.execute_graphql.assert_called_once()

    call = sweep._service_api.execute_graphql.call_args
    mutation = call.args[0]
    variables = call.kwargs["variables"]

    # The mutation targets the new endpoint and identifies the sweep by id.
    assert "enqueueSweepRun" in mutation
    assert "$id: ID!" in mutation
    # The sweep is identified by its global node id, not its short name.
    assert variables == {
        "id": "sweep-node-id",
        "config": json.dumps(config),
        "displayName": "my-run",
    }


def test_enqueue_run_defaults_display_name_to_none(mocker):
    """display_name is optional and defaults to None in the request variables."""
    sweep = _make_sweep(
        mocker,
        feature_enabled=True,
        graphql_response={
            "enqueueSweepRun": {"id": "run-node-id", "runQueueItemId": None}
        },
    )

    sweep.enqueue_run({"lr": {"value": 0.1}})

    variables = sweep._service_api.execute_graphql.call_args.kwargs["variables"]
    assert variables["displayName"] is None
    assert variables["id"] == "sweep-node-id"
    assert variables["config"] == json.dumps({"lr": {"value": 0.1}})


def test_enqueue_run_raises_when_feature_unsupported(mocker):
    """Without the SWEEPS_LOCAL_SCHEDULER feature, enqueue_run raises and no
    mutation is sent."""
    sweep = _make_sweep(mocker, feature_enabled=False)

    with pytest.raises(UnsupportedError, match="not supported on this wandb server"):
        sweep.enqueue_run({"lr": {"value": 0.1}})

    sweep._service_api.execute_graphql.assert_not_called()


def _api_failing_with(http_status: int) -> Mock:
    api = Mock()
    response = apb.ApiErrorResponse(message="error", http_status=http_status)
    api._service_api.execute_graphql.side_effect = WandbApiFailedError(
        response.message, response
    )
    return api


def test_agent_heartbeat_with_no_agent_id_fails():
    with pytest.raises(ValueError):
        _agent_heartbeat(Mock(), None, {}, {})


def test_agent_heartbeat_raises_sweep_not_found_on_404():
    with pytest.raises(SweepNotFoundError):
        _agent_heartbeat(_api_failing_with(404), "test-agent-id", {}, {})


def test_agent_heartbeat_returns_empty_on_non_404_error():
    assert _agent_heartbeat(_api_failing_with(500), "test-agent-id", {}, {}) == []


def _agent_runs_response(
    run_names: list[str], *, has_next_page: bool
) -> dict[str, object]:
    return {
        "project": {
            "sweep": {
                "agent": {
                    "runs": {
                        "pageInfo": {
                            "__typename": "PageInfo",
                            "endCursor": f"cursor-{run_names[-1]}",
                            "hasNextPage": has_next_page,
                        },
                        "edges": [
                            {
                                "cursor": f"cursor-{name}",
                                "node": {
                                    "id": f"storage-{name}",
                                    "tags": None,
                                    "name": name,
                                    "displayName": None,
                                    "sweepName": "sweep-name",
                                    "state": "finished",
                                    "group": None,
                                    "jobType": None,
                                    "commit": None,
                                    "readOnly": False,
                                    "createdAt": "2026-01-01T00:00:00Z",
                                    "heartbeatAt": None,
                                    "description": None,
                                    "notes": None,
                                    "historyLineCount": 1,
                                    "user": {
                                        "name": "test-user",
                                        "username": "test-user",
                                    },
                                },
                            }
                            for name in run_names
                        ],
                    }
                }
            }
        }
    }


def test_agent_runs_paginates(mocker):
    service_api = mocker.MagicMock()
    responses = iter(
        [
            _agent_runs_response(["run-1", "run-2"], has_next_page=True),
            _agent_runs_response(["run-3"], has_next_page=False),
        ]
    )
    requests = []

    def execute_graphql(_query, variables):
        requests.append(dict(variables))
        return next(responses)

    service_api.execute_graphql.side_effect = execute_graphql
    agent = Agent(
        service_api,
        attrs={"id": "agent-id", "name": "agent-name", "totalRuns": 3},
        entity="entity",
        project="project",
        sweep_id="sweep-name",
    )

    runs = list(agent.runs(per_page=2))

    assert [run.id for run in runs] == ["run-1", "run-2", "run-3"]
    assert {run.state for run in runs} == {"finished"}
    assert service_api.execute_graphql.call_count == 2
    first_variables, second_variables = requests
    assert first_variables["first"] == 2
    assert first_variables["after"] is None
    assert second_variables["first"] == 2
    assert second_variables["after"] == "cursor-run-2"


def test_upsert_sweep():
    api = Mock()
    api.settings = {"entity": None, "project": None}
    api._service_api.execute_graphql.return_value = {
        "upsertSweep": {"sweep": {"name": "test-sweep"}}
    }
    sweep_config = {
        "job": "fake-job:v1",
        "method": "bayes",
        "metric": {"name": "loss_metric", "goal": "minimize"},
        "parameters": {
            "epochs": {"value": 1},
            "increment": {"values": [0.1, 0.2, 0.3]},
        },
    }

    sweep, warnings = _upsert_sweep(
        api, sweep_config, prior_runs=["abc", "def"], display_name="test-display-name"
    )

    assert (sweep, warnings) == ({"name": "test-sweep"}, [])
    (mutation,), kwargs = api._service_api.execute_graphql.call_args
    assert "$priorRunsFilters: JSONString" in mutation
    assert "priorRunsFilters: $priorRunsFilters" in mutation
    assert (
        kwargs["variables"]["priorRunsFilters"]
        == '{"$or": [{"name": "abc"}, {"name": "def"}]}'
    )
    assert "$displayName: String" in mutation
    assert "displayName: $displayName" in mutation
    assert kwargs["variables"]["displayName"] == "test-display-name"


def test_upsert_sweep_does_not_drop_launch_scheduler_on_errors():
    api = Mock()
    api.settings = {"entity": None, "project": None}
    api._service_api.execute_graphql.side_effect = WandbApiFailedError(
        "could not find launch queue project"
    )

    with pytest.raises(CommError):
        _upsert_sweep(api, {"method": "grid", "parameters": {}}, launch_scheduler="{}")

    assert api._service_api.execute_graphql.call_count == 2


def test_created_sweep_can_be_read_with_same_api(monkeypatch):
    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)
    api = Mock()
    api.settings = {"entity": None, "project": None}
    api._service_api.execute_graphql.side_effect = [
        {
            "upsertSweep": {
                "sweep": {
                    "name": "test-sweep",
                    "project": {
                        "name": "uncategorized",
                        "entity": {"name": "test-entity"},
                    },
                }
            }
        },
        {"project": {"sweep": {"runs": {"edges": []}}}},
    ]

    sweep, _ = _upsert_sweep(api, {"method": "grid", "parameters": {}})
    _sweep_with_runs(api, sweep["name"], "{}")

    assert api._service_api.execute_graphql.call_args.kwargs["variables"] == {
        "entity": "test-entity",
        "project": "uncategorized",
        "sweep": "test-sweep",
        "specs": "{}",
    }
