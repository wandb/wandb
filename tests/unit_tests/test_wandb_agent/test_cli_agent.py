from __future__ import annotations

import contextlib
import io
import itertools
import json
import multiprocessing
import pathlib
from unittest import mock

import pytest
import yaml
from wandb import env, wandb_agent
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps import SweepNotFoundError
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


class _AgentWithScriptedExitCodes(Agent):
    """Injects mock child processes that report scripted exit codes in order."""

    def __init__(
        self,
        *args,
        exit_codes: list[int],
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._exit_codes = list(exit_codes)
        self.started_run_ids: list[str] = []

    def _command_run(self, command):
        self.started_run_ids.append(command["run_id"])
        exit_code = self._exit_codes.pop(0) if self._exit_codes else 0
        proc = mock.MagicMock()
        # Report the run as still going once, then settle on its exit code for
        # every later poll, including the ones the termination cascade makes.
        proc.poll = mock.Mock(
            side_effect=itertools.chain([None], itertools.repeat(exit_code))
        )
        self._run_processes[command["run_id"]] = proc


def _scripted_failure_agent(
    wandb_agent_env: WandbAgentTestEnv,
    *,
    exit_codes: list[int],
    max_consecutive_failed_runs: int | None,
    count: int | None = None,
) -> _AgentWithScriptedExitCodes:
    """Build a CLI agent whose runs exit with `exit_codes`, in order."""
    wandb_agent_env.patch_cli()
    api = wandb_agent_env.mock_api(for_cli=True)
    api.agent_heartbeat.side_effect = sequence_heartbeat_responses(
        *[
            [heartbeat_run_command(f"run-{i}", {"a": {"value": i}})]
            for i in range(len(exit_codes))
        ]
    )
    return _AgentWithScriptedExitCodes(
        api,
        multiprocessing.Queue(),
        sweep_id=wandb_agent_env.cli_sweep_id,
        function=None,
        in_jupyter=False,
        count=count,
        max_consecutive_failed_runs=max_consecutive_failed_runs,
        exit_codes=exit_codes,
    )


def test_cli_agent_stops_after_max_consecutive_failed_runs(
    wandb_agent_env: WandbAgentTestEnv,
):
    """Two back-to-back failures shut the agent down when the limit is 2."""
    agent = _scripted_failure_agent(
        wandb_agent_env,
        exit_codes=[1, 1, 1],
        max_consecutive_failed_runs=2,
    )

    termerrors = []
    wandb_agent_env.monkeypatch.setattr(
        wandb_agent.wandb, "termerror", termerrors.append
    )
    agent.run()

    assert "Detected 2 consecutive failed runs, shutting down." in termerrors


def test_cli_agent_below_max_consecutive_failed_runs_keeps_going(
    wandb_agent_env: WandbAgentTestEnv,
):
    """One failure short of the limit does not stop the agent."""
    agent = _scripted_failure_agent(
        wandb_agent_env,
        exit_codes=[1, 1],
        max_consecutive_failed_runs=3,
        count=2,
    )

    termerrors = []
    wandb_agent_env.monkeypatch.setattr(
        wandb_agent.wandb, "termerror", termerrors.append
    )
    agent.run()

    assert agent.started_run_ids == ["run-0", "run-1"]
    assert not any("consecutive failed runs" in message for message in termerrors)


def test_cli_agent_successful_run_resets_consecutive_failures(
    wandb_agent_env: WandbAgentTestEnv,
):
    """A run that exits 0 clears the failure streak, so fail/succeed/fail is safe."""
    agent = _scripted_failure_agent(
        wandb_agent_env,
        exit_codes=[1, 0, 1],
        max_consecutive_failed_runs=2,
        count=3,
    )

    termerrors = []
    wandb_agent_env.monkeypatch.setattr(
        wandb_agent.wandb, "termerror", termerrors.append
    )
    agent.run()

    assert agent.started_run_ids == ["run-0", "run-1", "run-2"]
    assert not any("consecutive failed runs" in message for message in termerrors)


def test_cli_agent_consecutive_failure_check_disabled_by_default(
    wandb_agent_env: WandbAgentTestEnv,
):
    """Without the flag, consecutive failures never stop the agent."""
    agent = _scripted_failure_agent(
        wandb_agent_env,
        exit_codes=[1, 1],
        max_consecutive_failed_runs=None,
        count=2,
    )

    termerrors = []
    wandb_agent_env.monkeypatch.setattr(
        wandb_agent.wandb, "termerror", termerrors.append
    )
    agent.run()

    assert agent.started_run_ids == ["run-0", "run-1"]
    assert not any("consecutive failed runs" in message for message in termerrors)


def test_cli_command_forwards_max_consecutive_failed_runs():
    """`wandb agent --max-consecutive-failed-runs N` reaches the agent."""
    from click.testing import CliRunner
    from wandb.cli import cli

    with mock.patch.object(cli.wandb_agent, "agent") as agent_mock:
        result = CliRunner().invoke(
            cli.agent, ["--max-consecutive-failed-runs", "3", "sweep-id"]
        )

    assert result.exit_code == 0, result.output
    assert agent_mock.call_args.kwargs["max_consecutive_failed_runs"] == 3


def test_cli_command_max_consecutive_failed_runs_defaults_to_none():
    """Omitting the flag leaves the check disabled."""
    from click.testing import CliRunner
    from wandb.cli import cli

    with mock.patch.object(cli.wandb_agent, "agent") as agent_mock:
        result = CliRunner().invoke(cli.agent, ["sweep-id"])

    assert result.exit_code == 0, result.output
    assert agent_mock.call_args.kwargs["max_consecutive_failed_runs"] is None


@pytest.mark.parametrize("value", ["0", "-1"])
def test_cli_command_rejects_non_positive_max_consecutive_failed_runs(value: str):
    """A limit below 1 is a usage error rather than an agent that never runs."""
    from click.testing import CliRunner
    from wandb.cli import cli

    with mock.patch.object(cli.wandb_agent, "agent") as agent_mock:
        result = CliRunner().invoke(
            cli.agent, ["--max-consecutive-failed-runs", value, "sweep-id"]
        )

    assert result.exit_code != 0
    agent_mock.assert_not_called()
