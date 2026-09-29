"""Integration tests for the run_messages mechanism."""

import pytest
import wandb

from tests.fixtures.mock_wandb_log import MockWandbLog


@pytest.mark.parametrize("mode", ["online", "offline"])
@pytest.mark.usefixtures("user")  # online mode requires an authenticated user
def test_prints_run_messages(mock_wandb_log: MockWandbLog, mode: str):
    with wandb.init(mode=mode) as run:
        run.log({"x": 3}, step=3)
        run.log({"x": 2}, step=2)

    mock_wandb_log.assert_warned(
        "Tried to log to step 2 that is less than the current step 3",
    )
