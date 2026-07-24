import json

import pytest
from wandb.apis.public.sweeps import Sweep
from wandb.errors import UnsupportedError
from wandb.proto import wandb_internal_pb2 as pb


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
