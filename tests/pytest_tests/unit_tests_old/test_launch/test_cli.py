import json

import pytest
import wandb
from wandb.cli import cli


@pytest.mark.parametrize("stop_method", ["stop", "cancel"])
def test_sweep_pause(runner, mock_server, test_settings, stop_method):
    with runner.isolated_filesystem():
        sweep_config = {
            "name": "My Sweep",
            "method": "grid",
            "parameters": {"parameter1": {"values": [1, 2, 3]}},
        }
        sweep_id = wandb.sweep(sweep_config)
        assert sweep_id == "test"
        assert runner.invoke(cli.sweep, ["--pause", sweep_id]).exit_code == 0
        assert runner.invoke(cli.sweep, ["--resume", sweep_id]).exit_code == 0
        if stop_method == "stop":
            assert runner.invoke(cli.sweep, ["--stop", sweep_id]).exit_code == 0
        else:
            assert runner.invoke(cli.sweep, ["--cancel", sweep_id]).exit_code == 0


def test_sweep_scheduler(runner, mock_server, test_settings):
    with runner.isolated_filesystem():
        with open("config.json", "w") as f:
            json.dump(
                {
                    "queue": "default",
                    "resource": "local-process",
                    "job": "mock-launch-job",
                    "scheduler": {
                        "resource": "local-process",
                    },
                },
                f,
            )
        sweep_config = {
            "name": "My Sweep",
            "method": "grid",
            "parameters": {"parameter1": {"values": [1, 2, 3]}},
        }
        sweep_id = wandb.sweep(sweep_config)
        assert sweep_id == "test"
        assert (
            runner.invoke(
                cli.launch_sweep,
                ["config.json", "--resume_id", sweep_id],
            ).exit_code
            == 0
        )
