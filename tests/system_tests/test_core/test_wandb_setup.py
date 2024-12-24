import json
import os
from unittest import mock

import pytest
import wandb


@pytest.mark.wandb_core_only
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


@pytest.mark.wandb_core_only
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
