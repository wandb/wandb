import pytest
from wandb.errors import CommError
from wandb.apis import internal


def test_agent_heartbeat_with_no_agent_id_fails(test_settings):
    a = internal.Api()
    with pytest.raises(ValueError):
        a.agent_heartbeat(None, {}, {})


def test_run_state(test_settings):
    _api = internal.Api()
    with pytest.raises(CommError):
        _api.get_run_state("test_entity", None, "test_run")
    with pytest.raises(CommError):
        _api.get_run_state("test_entity", "test_project", None)
