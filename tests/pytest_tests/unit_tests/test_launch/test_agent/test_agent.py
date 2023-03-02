from unittest.mock import MagicMock

from wandb.sdk.launch.agent.agent import LaunchAgent


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


def _setup(mocker):
    mocker.api = MagicMock()
    mock_agent_response = {"name": "test-name", "stopPolling": False}
    mocker.api.get_launch_agent = MagicMock(return_value=mock_agent_response)
    mocker.api.ack_run_queue_item = MagicMock(side_effect=KeyboardInterrupt)
    mocker.termlog = MagicMock()
    mocker.termerror = MagicMock()
    mocker.patch("wandb.termlog", mocker.termlog)
    mocker.patch("wandb.termerror", mocker.termerror)
