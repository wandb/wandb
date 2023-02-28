from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.utils import LaunchError


def _setup(mocker):
    mocker.api = MagicMock()
    mock_agent_response = {"name": "test-name", "stopPolling": False}
    mocker.api.get_launch_agent = MagicMock(return_value=mock_agent_response)
    mocker.api.ack_run_queue_item = MagicMock(side_effect=KeyboardInterrupt)
    mocker.termlog = MagicMock()
    mocker.termerror = MagicMock()
    mocker.patch("wandb.termlog", mocker.termlog)
    mocker.patch("wandb.termerror", mocker.termerror)


def test_loop_capture_stack_trace(mocker):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent.run_job = MagicMock()
    agent.run_job.side_effect = [None, None, Exception("test exception")]
    agent.pop_from_queue = MagicMock(return_value=MagicMock())

    agent.loop()

    assert "Traceback (most recent call last):" in mocker.termerror.call_args[0][0]


@pytest.mark.parametrize(
    "num_schedulers",
    [0, -1, 1000000, "8"],
)
def test_max_scheduler_setup(mocker, num_schedulers):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
        "max_schedulers": num_schedulers,
    }
    agent = LaunchAgent(api=mocker.api, config=mock_config)

    if num_schedulers == -1:
        num_schedulers = float("inf")
    elif type(num_schedulers) is str:
        num_schedulers = int(num_schedulers)

    assert agent._max_schedulers == max(0, num_schedulers)


@pytest.mark.parametrize(
    "num_schedulers",
    [-29, "weird"],
)
def test_max_scheduler_setup_fail(mocker, num_schedulers):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
        "max_schedulers": num_schedulers,
    }

    with pytest.raises(LaunchError):
        LaunchAgent(api=mocker.api, config=mock_config)
