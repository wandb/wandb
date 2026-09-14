import json
from unittest.mock import MagicMock

import pytest
from wandb.errors import CommError


def test_push_to_run_queue_by_name(test_api):
    mock_run_spec = {"test-key": "test-value"}
    mock_gql_response = {"pushToRunQueueByName": {"runSpec": json.dumps(mock_run_spec)}}
    test_api._service_api.execute_graphql = MagicMock(return_value=mock_gql_response)

    push_kwargs = {
        "entity": "test-entity",
        "project": "test-project",
        "queue_name": "test-queue",
        "run_spec": "{}",
        "template_variables": None,
        "priority": 2,
    }

    resp = test_api.push_to_run_queue_by_name(**push_kwargs)

    assert resp == {"runSpec": mock_run_spec}
    call_args = test_api._service_api.execute_graphql.call_args[0]
    assert "$priority: Int" in call_args[0]
    assert "priority: $priority" in call_args[0]
    assert call_args[1] == {
        "entityName": "test-entity",
        "projectName": "test-project",
        "queueName": "test-queue",
        "runSpec": "{}",
        "priority": 2,
    }


def test_get_run_state_invalid_kwargs(test_api):
    test_api._service_api.execute_graphql = lambda *args, **kwargs: {}

    with pytest.raises(CommError, match="Error fetching run state"):
        test_api.get_run_state("test_entity", None, "test_run")
