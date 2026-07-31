"""Tests for the CLI sweeps agent."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import wandb
from wandb import wandb_agent


def test_agent_writes_args_json_file_under_wandb_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    wandb_dir = tmp_path / "wandb-out"
    monkeypatch.setenv(wandb.env.DIR, str(wandb_dir))
    monkeypatch.setenv(wandb.env.SWEEP_ID, "test")

    with patch.object(wandb_agent, "AgentProcess") as agent_process:
        agent = wandb_agent.Agent(Mock(), Mock(), sweep_id="test")
        agent._sweep_command = ["${args_json_file}"]
        # If we don't support custom wandb_dirs, this will throw an error.
        agent._command_run(
            {
                "run_id": "run",
                "program": "train.py",
                "args": {"param1": {"value": 1}},
            }
        )

    args_json_path = wandb_dir / "wandb/sweep-test/config-run.json"
    assert json.loads(args_json_path.read_text()) == {"param1": 1}
    assert agent_process.call_args.kwargs["command"] == [str(args_json_path)]
