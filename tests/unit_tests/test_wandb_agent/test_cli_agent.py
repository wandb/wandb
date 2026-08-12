from __future__ import annotations

import contextlib
import io
import json
import multiprocessing
import pathlib
from unittest import mock

import pytest
import yaml
from wandb import env, wandb_agent
from wandb.sdk.launch.sweeps import SweepNotFoundError
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.wandb_agent import Agent

from .conftest import (
    WandbAgentTestEnv,
    heartbeat_run_command,
    sequence_heartbeat_responses,
    sweep_not_running_api_error,
)


class _AgentWithFakeChildProcess(Agent):
    """Injects a mock subprocess so CLI agent tests do not spawn real training jobs."""

    def _command_run(self, command):
        proc = mock.MagicMock()
        proc.last_sigterm_time = None
        proc.poll = mock.Mock(side_effect=[None, 0])
        self._run_processes[command["run_id"]] = proc


def test_cli_agent_sweep_not_found_no_running_raises(
    wandb_agent_env: WandbAgentTestEnv,
):
    """404 on heartbeat with no child runs re-raises SweepNotFoundError (CLI subprocess agent)."""
    wandb_agent_env.patch_cli()
    api = wandb_agent_env.mock_api(for_cli=True)
    api.agent_heartbeat.side_effect = SweepNotFoundError("Sweep not found")

    agent = Agent(
        api,
        multiprocessing.Queue(),
        sweep_id=wandb_agent_env.cli_sweep_id,
        function=None,
        in_jupyter=False,
        count=None,
    )

    with pytest.raises(SweepNotFoundError):
        agent.run()


def test_cli_agent_fails_fast_on_terminal_sweep_state(
    wandb_agent_env: WandbAgentTestEnv,
):
    """A 400 from register_agent (terminal sweep) propagates without retrying (CLI agent)."""
    wandb_agent_env.patch_cli()
    api = wandb_agent_env.mock_api(for_cli=True)
    api.register_agent.side_effect = sweep_not_running_api_error(
        wandb_agent_env.cli_sweep_id
    )

    agent = wandb_agent_env.make_cli_agent(api, count=1)

    with pytest.raises(WandbApiFailedError, match="is not running"):
        agent.run()

    # Fail fast: registration is attempted exactly once, and the agent never
    # reaches the heartbeat loop.
    assert api.register_agent.call_count == 1
    api.agent_heartbeat.assert_not_called()


def test_agent_config_whitespace_cli_agent(wandb_agent_env):
    pathlib.Path("test.py").write_text(
        "import wandb\n"
        "\n"
        "run = wandb.init(mode='disabled')\n"
        "assert run.config['a'] == 'one two'\n"
        "assert run.config['b'] == 'three four'\n"
        "run.finish()\n"
    )

    sweep_config = {
        "name": "My Sweep",
        "program": "test.py",
        "method": "grid",
        "parameters": {
            "a": {"values": ["one two"]},
            "b": {"value": "three four"},
        },
    }

    api = wandb_agent_env.mock_api(for_cli=True)
    api.sweep.return_value = {"config": yaml.dump(sweep_config)}
    api.agent_heartbeat.side_effect = sequence_heartbeat_responses(
        [
            heartbeat_run_command(
                "run-cli-whitespace",
                {
                    "a": {"value": "one two"},
                    "b": {"value": "three four"},
                },
                program="test.py",
            )
        ]
    )

    wandb_agent_env.run_cli_agent(api, count=1)


def test_agent_subprocess_with_import_readline(wandb_agent_env):
    """wandb.agent works safely when a subprocess imports readline."""
    script_path = (
        pathlib.Path(__file__).parent / "scripts" / "train_with_import_readline.py"
    )

    sweep_config = {
        "name": "Train with import readline",
        "method": "grid",
        "parameters": {"test_param": {"values": [1]}},
        "command": ["python", str(script_path)],
    }

    api = wandb_agent_env.mock_api(for_cli=True)
    api.sweep.return_value = {"config": yaml.dump(sweep_config)}
    api.agent_heartbeat.side_effect = sequence_heartbeat_responses(
        [
            heartbeat_run_command(
                "run-readline",
                {"test_param": {"value": 1}},
                program=str(script_path),
            )
        ]
    )

    wandb_agent_env.monkeypatch.setenv("WANDB_AGENT_MAX_INITIAL_FAILURES", "1")
    wandb_agent_env.monkeypatch.setenv("WANDB_MODE", "disabled")
    wandb_agent_env.run_cli_agent(api, count=1)


def test_cli_agent_sweep_not_found_waits_for_active_run(
    wandb_agent_env: WandbAgentTestEnv,
):
    """404 does not raise while a mock child process is still reported running."""
    wandb_agent_env.patch_cli()
    api = wandb_agent_env.mock_api(for_cli=True)
    api.agent_heartbeat.side_effect = sequence_heartbeat_responses(
        [
            heartbeat_run_command(
                "cli-sweep-deleted-run",
                {"a": {"value": 1}},
            ),
        ],
        SweepNotFoundError("Sweep not found"),
    )

    agent = _AgentWithFakeChildProcess(
        api,
        multiprocessing.Queue(),
        sweep_id=wandb_agent_env.cli_sweep_id,
        function=None,
        in_jupyter=False,
        count=None,
    )

    captured = io.StringIO()
    with contextlib.redirect_stderr(captured):
        agent.run()

    err = captured.getvalue()
    assert "Sweep was deleted or agent was not found" in err
    assert "Active runs will be allowed to finish before the agent exits" in err


def test_agent_writes_args_json_file_under_wandb_dir(
    wandb_agent_env: WandbAgentTestEnv,
):
    wandb_agent_env.patch_cli()
    api = wandb_agent_env.mock_api(for_cli=True)
    wandb_dir = wandb_agent_env.tmp_path / "wandb-out"
    wandb_agent_env.monkeypatch.setenv(env.DIR, str(wandb_dir))

    with mock.patch.object(wandb_agent, "AgentProcess") as agent_process:
        agent = wandb_agent_env.make_cli_agent(api)
        agent._sweep_command = ["${args_json_file}"]
        # If we don't support custom wandb_dirs, this will throw an error.
        agent._command_run(
            {
                "run_id": "run",
                "program": "train.py",
                "args": {"param1": {"value": 1}},
            }
        )

    args_json_path = (
        wandb_dir / f"wandb/sweep-{wandb_agent_env.cli_sweep_id}/config-run.json"
    )
    assert json.loads(args_json_path.read_text()) == {"param1": 1}
    assert agent_process.call_args.kwargs["command"] == [str(args_json_path)]
