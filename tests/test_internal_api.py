import pytest
from unittest.mock import MagicMock

from wandb.errors import CommError
from wandb.apis import internal

def test_agent_heartbeat_with_no_agent_id_fails(test_settings):
    a = internal.Api()
    with pytest.raises(ValueError):
        a.agent_heartbeat(None, {}, {})


def test_get_run_state_invalid_kwargs(live_mock_server, test_settings):
    from wandb.sdk.internal.internal_api import Api
    with pytest.raises(CommError):
        # Api.execute = MagicMock(return_value={})
        internal.Api.api.execute = MagicMock(return_value={})
        _api = internal.Api()
        _api.get_run_state("test_entity", None, "test_run")
    with pytest.raises(CommError):
        # Api.execute = MagicMock(return_value={"project":{}})
        internal.Api.api.execute = MagicMock(return_value={"project":{}})
        _api = internal.Api()
        _api.get_run_state("test_entity", "test_project", None)


def test_get_run_state(test_settings):
    _api = internal.Api()
    res = _api.get_run_state("test", "test", "test")
    assert res == "running", "Test run must have state running"
