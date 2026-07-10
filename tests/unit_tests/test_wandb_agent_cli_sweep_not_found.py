"""Sweep-not-found behavior for wandb_agent.Agent (CLI subprocess agent)."""

from __future__ import annotations

import contextlib
import io
import multiprocessing
from unittest import mock

import pytest
import wandb
from wandb.sdk.launch.sweeps import SweepNotFoundError
from wandb.wandb_agent import Agent


def _patch_cli_agent_loop(monkeypatch, tmp_path):
    """Avoid slow queue reads and noisy teardown when unit-testing wandb_agent.Agent."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(wandb.env.SWEEP_ID, "sweep-cli-test")
    monkeypatch.setenv(wandb.env.DIR, str(tmp_path))
    monkeypatch.setattr(
        "wandb.wandb_agent.util.read_many_from_queue",
        lambda q, max_items, queue_timeout: [],
    )
    monkeypatch.setattr(wandb, "teardown", lambda *args, **kwargs: None)


def _mock_api_for_cli_agent():
    api = mock.MagicMock()
    api.sweep.return_value = None
    api.register_agent.return_value = {"id": "agent-test-id"}
    return api


class _AgentWithFakeChildProcess(Agent):
    """Injects a mock subprocess so CLI agent tests do not spawn real training jobs."""

    def _command_run(self, command):
        proc = mock.MagicMock()
        proc.last_sigterm_time = None
        proc.poll = mock.Mock(side_effect=[None, 0])
        self._run_processes[command["run_id"]] = proc


def test_cli_agent_sweep_not_found_no_running_raises(monkeypatch, tmp_path):
    """404 on heartbeat with no child runs re-raises SweepNotFoundError (CLI subprocess agent)."""
    _patch_cli_agent_loop(monkeypatch, tmp_path)
    api = _mock_api_for_cli_agent()
    api.agent_heartbeat.side_effect = SweepNotFoundError("Sweep not found")

    agent = Agent(
        api,
        multiprocessing.Queue(),
        sweep_id="sweep-cli-test",
        function=None,
        in_jupyter=False,
        count=None,
    )

    with pytest.raises(SweepNotFoundError):
        agent.run()


def test_cli_agent_sweep_not_found_waits_for_active_run(monkeypatch, tmp_path):
    """404 does not raise while a mock child process is still reported running."""
    _patch_cli_agent_loop(monkeypatch, tmp_path)
    api = _mock_api_for_cli_agent()
    api.agent_heartbeat.side_effect = [
        [
            {
                "type": "run",
                "run_id": "cli-sweep-deleted-run",
                "args": {"a": {"value": 1}},
                "program": "train.py",
            }
        ],
        SweepNotFoundError("Sweep not found"),
    ]

    agent = _AgentWithFakeChildProcess(
        api,
        multiprocessing.Queue(),
        sweep_id="sweep-cli-test",
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
