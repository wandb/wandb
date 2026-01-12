from __future__ import annotations

import asyncio
import json
import os
from unittest import mock

import pytest
import wandb
from wandb.sdk import wandb_setup
from wandb.sdk.lib import asyncio_manager


def test_service_logging_level_debug():
    """Test the service logging is debug.

    Verifies that the service logging level is set to DEBUG when the
    `WANDB_DEBUG` environment variable is set.
    """
    with mock.patch.dict(os.environ, {"WANDB_DEBUG": "true"}):
        with wandb.init(mode="offline") as run:
            run.log({"foo": "bar"})

        # load the debug logs of the service process
        with open(run.settings.log_internal) as f:
            debug_log = [json.loads(line) for line in f]

        levels = {log_entry["level"] for log_entry in debug_log}
        assert "DEBUG" in levels


def test_service_logging_level_info():
    """Test the service logging is info.

    Verifies that the service logging level is set to INFO when the
    `WANDB_DEBUG` environment variable is not set.
    """
    with mock.patch.dict(os.environ, {"WANDB_DEBUG": "false"}):
        with wandb.init(mode="offline") as run:
            run.log({"foo": "bar"})

        # load the debug logs of the service process
        with open(run.settings.log_internal) as f:
            debug_log = [json.loads(line) for line in f]

        levels = {log_entry["level"] for log_entry in debug_log}
        assert "DEBUG" not in levels


def test_remove_active_run_twice():
    run = wandb.init(mode="offline")
    wl = wandb.setup()

    assert run is wl.most_recent_active_run
    wl.remove_active_run(run)
    wl.remove_active_run(run)  # This must not raise an error.

    assert wl.most_recent_active_run is None


def test_setup_uses_config_dir_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("WANDB_CONFIG_DIR", str(tmp_path))
    with mock.patch.dict(os.environ, {"WANDB_CONFIG_DIR": str(tmp_path)}):
        setup = wandb.setup()
        assert setup.settings.settings_system == str(tmp_path / "settings")


def test_teardown_joins_asyncer():
    asyncer = wandb_setup.singleton().asyncer
    wandb.teardown()

    with pytest.raises(asyncio_manager.AlreadyJoinedError):
        asyncer.run(lambda: asyncio.sleep(0))
