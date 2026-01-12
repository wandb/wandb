from __future__ import annotations

import json
import os

import wandb
from wandb.cli import cli


def test_agent_queues_config(runner, monkeypatch, user):
    run = wandb.init(project="model-registry")
    run.finish()
    monkeypatch.setattr(
        wandb.sdk.launch._launch,
        "LAUNCH_CONFIG_FILE",
        os.path.join("./config/wandb/launch-config.yaml"),
    )
    launch_config = {"builder": {"type": "docker"}, "queues": ["q1", "q2"]}

    with runner.isolated_filesystem():
        os.makedirs(os.path.expanduser("./config/wandb"))
        with open(os.path.expanduser("./config/wandb/launch-config.yaml"), "w") as f:
            json.dump(launch_config, f)
        result = runner.invoke(
            cli.launch_agent,
            [
                "--entity",
                user,
            ],
        )
        assert result.exit_code != 0
        assert "Not all of requested queues (q1, q2) found" in result.output
