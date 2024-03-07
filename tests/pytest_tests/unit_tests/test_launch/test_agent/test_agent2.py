import pytest
from unittest.mock import MagicMock, AsyncMock

from wandb.sdk.launch.agent2.agent import LaunchAgent2

@pytest.fixture
def fresh_agent():
    def reset():
        LaunchAgent2._instance = None
        LaunchAgent2._initialized = False
        LaunchAgent2._controller_impls = {}
        
    reset()
    yield
    reset()
    
@pytest.fixture
def common_setup(mocker):
    mocker.api = MagicMock()
    
    mocker.api.jobset_introspection = MagicMock(return_value={"JobSetDiffType": {"name": "JobSetDiff"}})
    mock_agent_response = {"name": "test-name", "stopPolling": False}
    mocker.api.get_launch_agent = MagicMock(return_value=mock_agent_response)
    mocker.api.fail_run_queue_item = MagicMock(side_effect=KeyboardInterrupt)
    
    mocker.termlog = MagicMock()
    mocker.termwarn = MagicMock()
    mocker.termerror = MagicMock()
    mocker.wandb_init = MagicMock()
    mocker.patch("wandb.termlog", mocker.termlog)
    mocker.patch("wandb.termwarn", mocker.termwarn)
    mocker.patch("wandb.termerror", mocker.termerror)
    mocker.patch("wandb.init", mocker.wandb_init)

    mocker.status = MagicMock()
    mocker.status.state = "running"
    mocker.run = MagicMock()

    mocker.run.get_status = AsyncMock(return_value=mocker.status)
    mocker.runner = MagicMock()

    async def _mock_runner_run(*args, **kwargs):
        return mocker.run

    mocker.runner.run = _mock_runner_run
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.runner_from_config",
        return_value=mocker.runner,
    )
    
def test_controller_registry(fresh_agent):
    test_controller = MagicMock()
    LaunchAgent2.register_controller_impl("test-exists", test_controller)
    
    assert LaunchAgent2.get_controller_for_jobset("test-exists") is test_controller
    with pytest.raises(ValueError):
        LaunchAgent2.get_controller_for_jobset("test-nothing")
        
def test_agent_singleton(common_setup, fresh_agent):
    api = MagicMock()
    
    config = {
        "entity": "test-entity",
        "project": "test-project",
        "queues": [],
    }
    
    agent1 = LaunchAgent2(api=api, config=config)
    agent2 = LaunchAgent2(api=api, config=config)
    
    assert agent1 is agent2
    assert isinstance(agent1, LaunchAgent2)
    