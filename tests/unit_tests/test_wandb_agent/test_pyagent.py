"""Unit tests for sweep agent behavior without a live backend."""

from __future__ import annotations

import contextlib
import io
import threading

import pytest
import wandb
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps import SweepNotFoundError

from .conftest import (
    DEFAULT_ENTITY,
    DEFAULT_PROJECT,
    DEFAULT_SWEEP_ID,
    heartbeat_run_command,
    sequence_heartbeat_responses,
    sweep_not_running_api_error,
)


def test_agent_basic(wandb_agent_env):
    sweep_ids = []
    sweep_configs = []
    sweep_resumed = []
    sweep_projects = []
    sweep_entities = []
    sweep_run_ids = []

    def train():
        run = wandb.init(mode="disabled")
        sweep_ids.append(run.sweep_id)
        sweep_configs.append(dict(run.config))
        sweep_resumed.append(run.resumed)
        run.finish()

    def train_merge():
        run = wandb.init(mode="disabled", config={"extra": 2})
        sweep_ids.append(run.sweep_id)
        sweep_configs.append(dict(run.config))
        run.finish()

    def train_ignored():
        run = wandb.init(
            mode="disabled",
            entity="ign",
            project="ignored",
            id="also_ignored",
            config={"a": "ignored"},
        )
        sweep_ids.append(run.sweep_id)
        sweep_entities.append(run.entity)
        sweep_projects.append(run.project)
        sweep_run_ids.append(run.id)
        sweep_configs.append(dict(run.config))
        run.finish()

    run_args = {"a": {"value": 1}}
    wandb_agent_env.monkeypatch.setenv("WANDB_CONSOLE", "off")
    for function in (train, train_merge, train_ignored):
        api = wandb_agent_env.mock_api()
        api.agent_heartbeat.side_effect = sequence_heartbeat_responses(
            [heartbeat_run_command(f"run-{len(sweep_configs)}", run_args)]
        )
        wandb_agent_env.run_pyagent(
            api,
            function,
            sweep_id=DEFAULT_SWEEP_ID,
            entity=DEFAULT_ENTITY,
            project=DEFAULT_PROJECT,
            mock_finish=False,
        )

    assert len(sweep_ids) == len(sweep_configs) == 3
    assert sweep_ids[0] == DEFAULT_SWEEP_ID
    assert sweep_configs[0] == {"a": 1}
    assert sweep_resumed[0] is False
    assert sweep_configs[1] == {"a": 1, "extra": 2}
    assert sweep_configs[2] == {"a": 1}
    assert sweep_projects[0] == DEFAULT_PROJECT
    assert sweep_entities[0] == DEFAULT_ENTITY
    assert sweep_run_ids[0] != "also_ignored"


def test_agent_config_whitespace_py_agent(wandb_agent_env):
    ran = False

    def train():
        nonlocal ran
        run = wandb.init(mode="disabled")
        assert run.config["a"] == "one two"
        assert run.config["b"] == "three four"
        assert run.config["c"] == '"five six"'
        run.finish()
        ran = True

    api = wandb_agent_env.mock_api()
    api.agent_heartbeat.side_effect = sequence_heartbeat_responses(
        [
            heartbeat_run_command(
                "run-whitespace",
                {
                    "a": {"value": "one two"},
                    "b": {"value": "three four"},
                    "c": {"value": '"five six"'},
                },
            )
        ]
    )

    wandb_agent_env.monkeypatch.setenv("WANDB_CONSOLE", "off")
    wandb_agent_env.run_pyagent(api, train, mock_finish=False)
    assert ran


def test_agent_exception(wandb_agent_env):
    def train():
        wandb.init(mode="disabled")
        raise Exception("Unexpected error")

    api = wandb_agent_env.mock_api()
    api.agent_heartbeat.side_effect = sequence_heartbeat_responses(
        [heartbeat_run_command("run-exception", {"a": {"value": 1}})]
    )

    captured_stderr = io.StringIO()
    with (
        wandb_agent_env.patch_pyagent(api, mock_finish=False),
        contextlib.redirect_stderr(captured_stderr),
    ):
        wandb_agent_env.make_pyagent(train, count=1).run()

    stderr_lines = captured_stderr.getvalue().splitlines()
    patterns = ["Traceback", "Exception: Unexpected error"]
    current_pattern = 0
    for line in stderr_lines:
        if line.startswith(patterns[current_pattern]):
            current_pattern += 1
            if current_pattern == len(patterns):
                break

    assert current_pattern == len(patterns), (
        f"Not found in stderr: '{patterns[current_pattern]}'"
    )


def test_agent_fails_fast_on_terminal_sweep_state(wandb_agent_env):
    """A 400 from register_agent (terminal sweep) propagates without retrying."""
    api = wandb_agent_env.mock_api()
    api.register_agent.side_effect = sweep_not_running_api_error()

    with (
        wandb_agent_env.patch_pyagent(api),
        pytest.raises(WandbApiFailedError, match="is not running"),
    ):
        wandb_agent_env.make_pyagent(function=lambda: None, count=1).run()

    # Fail fast: registration is attempted exactly once, and the agent never
    # reaches the heartbeat loop.
    assert api.register_agent.call_count == 1
    api.agent_heartbeat.assert_not_called()


def test_agent_sweep_deleted(wandb_agent_env):
    """Agent exits gracefully when sweep is deleted (404)."""
    api = wandb_agent_env.mock_api()
    api.agent_heartbeat.side_effect = SweepNotFoundError("Sweep not found")

    captured_stderr = io.StringIO()
    with (
        wandb_agent_env.patch_pyagent(api),
        contextlib.redirect_stderr(captured_stderr),
    ):
        wandb_agent_env.make_pyagent(function=lambda: None, count=1).run()

    stderr_output = captured_stderr.getvalue()
    assert "Sweep was deleted or agent was not found" in stderr_output


def test_agent_sweep_deleted_waits_for_in_flight_run(wandb_agent_env):
    """A 404 on heartbeat must not stop the agent while a trial thread is still running."""
    api = wandb_agent_env.mock_api()
    wait_msg = "in-process run will be allowed to finish"

    first_heartbeat_done = threading.Event()
    trial_in_user_code = threading.Event()
    waited_for_in_flight_run = threading.Event()
    termerrors: list[str] = []

    real_termerror = wandb.termerror

    def termerror_spy(message, *args, **kwargs):
        termerrors.append(message)
        if wait_msg in message:
            waited_for_in_flight_run.set()
        return real_termerror(message, *args, **kwargs)

    wandb_agent_env.monkeypatch.setattr(wandb, "termerror", termerror_spy)

    def train():
        trial_in_user_code.set()
        assert waited_for_in_flight_run.wait(timeout=30), (
            "agent did not log the in-flight wait message before timeout"
        )

    def agent_heartbeat_mock(agent_id, metrics, run_states):
        if not first_heartbeat_done.is_set():
            first_heartbeat_done.set()
            return [
                heartbeat_run_command("sweep-deleted-wait-run", {"a": {"value": 1}})
            ]
        if not trial_in_user_code.is_set():
            return []
        raise SweepNotFoundError("Sweep not found")

    api.agent_heartbeat.side_effect = agent_heartbeat_mock

    with wandb_agent_env.patch_pyagent(api):
        wandb_agent_env.make_pyagent(train, count=1).run()

    assert any(wait_msg in message for message in termerrors)
