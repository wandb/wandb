import json
from copy import deepcopy
from functools import partial
from unittest.mock import Mock

import pytest
from wandb.apis.public.projects import Project
from wandb.apis.public.sweeps import (
    Sweep,
    Sweeps,
    _agent_heartbeat,
    _sweep_with_runs,
    _upsert_sweep,
)
from wandb.errors import CommError, UnsupportedError
from wandb.proto import wandb_api_pb2 as apb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps import SweepNotFoundError


@pytest.fixture
def make_sweeps(mocker):
    service_api = mocker.Mock()
    service_api.feature_enabled.return_value = True
    return partial(Sweeps, service_api, "entity", "project"), service_api


def test_sweeps_reject_invalid_filters_before_requests(make_sweeps):
    create_sweeps, service_api = make_sweeps
    filters = {"tags": {"$all": [["sgd"], "test"]}}
    original_filters = deepcopy(filters)

    with pytest.raises(ValueError, match=r"filters\.tags\.\$all\[0\]"):
        create_sweeps(filters=filters)

    assert filters == original_filters
    service_api.feature_enabled.assert_not_called()
    service_api.execute_graphql.assert_not_called()


def test_sweeps_preserve_valid_filters(mocker):
    service_api = mocker.Mock()
    service_api.feature_enabled.return_value = True
    project = Project(service_api, "entity", "project", attrs={})
    filters = {"tags": {"$all": ["sgd"], "$nin": ["test-2"]}}

    sweeps = project.sweeps(filters=filters)

    assert sweeps.variables["filters"] == json.dumps(filters)


def test_sweeps_reject_filters_on_unsupported_server(make_sweeps):
    create_sweeps, service_api = make_sweeps
    service_api.feature_enabled.return_value = False

    with pytest.raises(UnsupportedError, match="Filtering sweeps is not supported"):
        create_sweeps(filters={"tags": {"$all": ["sgd"]}})

    service_api.feature_enabled.assert_called_once_with(pb.SWEEPS_QUERY_FILTERING)
    service_api.execute_graphql.assert_not_called()


def test_sweeps_allow_empty_filters_on_unsupported_server(make_sweeps):
    create_sweeps, service_api = make_sweeps
    service_api.feature_enabled.return_value = False

    sweeps = create_sweeps(filters=None)

    assert sweeps.variables["filters"] == "{}"
    service_api.feature_enabled.assert_called_once_with(pb.SWEEPS_QUERY_FILTERING)
    service_api.execute_graphql.assert_not_called()


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
