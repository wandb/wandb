import json
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.apis import internal
from wandb.errors import UnsupportedError


def test_create_run_queue(monkeypatch):
    _api = internal.Api()

    # prioritization_mode present on server
    _api.api.gql = MagicMock(return_value={"createRunQueue": "test-result"})
    _api.api.create_run_queue_introspection = MagicMock(return_value=(True, True, True))
    mock_gql = MagicMock(return_value="test-gql-resp")
    monkeypatch.setattr(wandb.sdk.internal.internal_api, "gql", mock_gql)

    kwargs = {
        "entity": "test-entity",
        "project": "test-project",
        "queue_name": "test-queue",
        "access": "test-access",
        "prioritization_mode": "test-prioritization-mode",
        "config_id": "test-config-id",
    }
    resp = _api.create_run_queue(**kwargs)
    assert resp == "test-result"
    _api.api.gql.assert_called_once_with(
        "test-gql-resp",
        {
            "entity": "test-entity",
            "project": "test-project",
            "queueName": "test-queue",
            "access": "test-access",
            "prioritizationMode": "test-prioritization-mode",
            "defaultResourceConfigID": "test-config-id",
        },
    )

    # prioritization_mode not present on server
    _api.api.gql = MagicMock(return_value={"createRunQueue": "test-result"})
    _api.api.create_run_queue_introspection = MagicMock(
        return_value=(True, True, False)
    )
    mock_gql = MagicMock(return_value="test-gql-resp")
    monkeypatch.setattr(wandb.sdk.internal.internal_api, "gql", mock_gql)

    # trying to use prioritization_mode gives error
    with pytest.raises(UnsupportedError):
        _api.create_run_queue(**kwargs)

    # able to create queue without prioritization_mode
    del kwargs["prioritization_mode"]
    resp = _api.create_run_queue(**kwargs)
    assert resp == "test-result"
    _api.api.gql.assert_called_once_with(
        "test-gql-resp",
        {
            "entity": "test-entity",
            "project": "test-project",
            "queueName": "test-queue",
            "access": "test-access",
            "defaultResourceConfigID": "test-config-id",
        },
    )


def test_push_to_run_queue_by_name(monkeypatch):
    _api = internal.Api()
    mock_run_spec = {"test-key": "test-value"}
    mock_gql_response = {"pushToRunQueueByName": {"runSpec": json.dumps(mock_run_spec)}}
    _api.api.gql = MagicMock(return_value=mock_gql_response)
    _api.api.push_to_run_queue_introspection = MagicMock()
    monkeypatch.setattr(wandb.sdk.internal.internal_api, "gql", lambda x: x)

    _api.api.server_push_to_run_queue_supports_priority = True
    push_kwargs = {
        "entity": "test-entity",
        "project": "test-project",
        "queue_name": "test-queue",
        "run_spec": "{}",
        "template_variables": None,
        "priority": 2,
    }

    resp = _api.api.push_to_run_queue_by_name(**push_kwargs)

    assert resp == {"runSpec": mock_run_spec}
    call_args = _api.api.gql.call_args[0]
    assert "$priority: Int" in call_args[0]
    assert "priority: $priority" in call_args[0]
    assert call_args[1] == {
        "entityName": "test-entity",
        "projectName": "test-project",
        "queueName": "test-queue",
        "runSpec": "{}",
        "priority": 2,
    }


def test_upsert_sweep(monkeypatch):
    _api = internal.Api()
    mock_sweep_name = "test-sweep"
    mock_display_name = "test-sweep-display-name"
    mock_gql_response = {"upsertSweep": {"sweep": {"name": mock_sweep_name}}}
    _api.api.gql = MagicMock(return_value=mock_gql_response)
    monkeypatch.setattr(wandb.sdk.internal.internal_api, "gql", lambda x: x)

    run_ids = ["abc", "def"]
    sweep_config = {
        "job": "fake-job:v1",
        "method": "bayes",
        "metric": {
            "name": "loss_metric",
            "goal": "minimize",
        },
        "parameters": {
            "epochs": {"value": 1},
            "increment": {"values": [0.1, 0.2, 0.3]},
        },
    }
    upsert_kwargs = {
        "config": sweep_config,
        "prior_runs": run_ids,
        "display_name": mock_display_name,
    }
    resp = _api.api.upsert_sweep(**upsert_kwargs)

    assert resp == (mock_sweep_name, [])
    call_args = _api.api.gql.call_args[0]
    call_kwargs = _api.api.gql.call_args.kwargs
    assert "$priorRunsFilters: JSONString" in call_args[0]
    assert "priorRunsFilters: $priorRunsFilters" in call_args[0]
    assert (
        call_kwargs["variable_values"]["priorRunsFilters"]
        == '{"$or": [{"name": "abc"}, {"name": "def"}]}'
    )
    assert "$displayName: String" in call_args[0]
    assert "displayName: $displayName" in call_args[0]
    assert call_kwargs["variable_values"]["displayName"] == mock_display_name
