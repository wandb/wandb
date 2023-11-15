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
