"""Unit tests for agent teardown behavior.

These tests verify that after wandb.agent() exits (normally or by exception),
global state is cleared so a subsequent wandb.init() creates a normal run,
not a sweep run. Open-source developers can use these to ensure changes
around agent teardown do not break this functionality.
"""

import os
from unittest import mock

import pytest
from wandb import env, wandb_agent
from wandb.sdk import wandb_setup


def test_agent_teardown_clears_sweep_id_on_exception(runner, monkeypatch):
    with runner.isolated_filesystem():
        """When agent() raises, the finally block must clear settings.sweep_id."""
        monkeypatch.setattr(
            "wandb.sdk.wandb_login._login",
            mock.Mock(side_effect=RuntimeError("login failed")),
        )
        # Ensure we have a singleton and pollute sweep_id to simulate prior sweep state.
        os.environ[env.SWEEP_ID] = "fake-sweep-id"
        settings = wandb_setup.singleton().settings
        assert settings.sweep_id == "fake-sweep-id"
        with pytest.raises(RuntimeError, match="login failed"):
            wandb_agent.agent("entity/project/sweep-id", function=None)

        assert settings.sweep_id is None, (
            "agent() finally must clear settings.sweep_id so the next init() is a normal run"
        )
        assert wandb_agent._is_running() is False


def test_agent_teardown_clears_sweep_id_on_normal_return(runner, monkeypatch):
    with runner.isolated_filesystem():
        """When agent() returns normally, the finally block must clear settings.sweep_id."""
        monkeypatch.setattr(
            "wandb.sdk.wandb_login._login", mock.Mock(return_value=None)
        )
        monkeypatch.setattr(
            "wandb.wandb_agent.run_agent",
            mock.Mock(return_value=None),
        )

        os.environ[env.SWEEP_ID] = "fake-sweep-id"
        settings = wandb_setup.singleton().settings
        assert settings.sweep_id == "fake-sweep-id"
        wandb_agent.agent("entity/project/sweep-id", function=None)

        assert settings.sweep_id is None, (
            "agent() finally must clear settings.sweep_id so the next init() is a normal run"
        )
        assert wandb_agent._is_running() is False
