import pytest
from wandb.errors import CommError
from wandb.apis import internal


def test_agent_heartbeat_with_no_agent_id_fails(test_settings):
    a = internal.Api()
    with pytest.raises(ValueError):
        a.agent_heartbeat(None, {}, {})


def test_get_run_state_invalid_kwargs():
    _api = internal.Api()
    with pytest.raises(CommError):
        _api.get_run_state("test_entity", None, "test_run")
    with pytest.raises(CommError):
        _api.get_run_state("test_entity", "test_project", None)


def test_get_run_state(test_settings):
    _api = internal.Api()
    res = _api.get_run_state("test", "test", "test")
    assert res == "running", "Test run must have state running"
