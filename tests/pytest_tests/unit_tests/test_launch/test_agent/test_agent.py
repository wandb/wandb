from unittest.mock import MagicMock

from wandb.sdk.launch.agent.agent import LaunchAgent


class TermSetupSettings:
    def __init__(self):
        self.silent = True
        self.show_info = True
        self.show_warnings = True
        self.show_errors = True


def test_loop_capture_stack_trace(mocker):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent.run_job = MagicMock()
    agent.run_job.side_effect = Exception("test exception")
    agent.pop_from_queue = MagicMock(return_value=MagicMock())

    agent.loop()

    call_args = mocker.termerror.call_args.args
    assert "Traceback (most recent call last):" in call_args[0]


def _setup(mocker):
    mocker.api = MagicMock()
    mock_agent_response = {"name": "test-name", "stopPolling": False}
    mocker.api.get_launch_agent = MagicMock(return_value=mock_agent_response)
    mocker.api.ack_run_queue_item = MagicMock(side_effect=KeyboardInterrupt)
    mocker.termlog = MagicMock()
    mocker.termerror = MagicMock()
    mocker.patch("wandb.termlog", mocker.termlog)
    mocker.patch("wandb.termerror", mocker.termerror)
