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
