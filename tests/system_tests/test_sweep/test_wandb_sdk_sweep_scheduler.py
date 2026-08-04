"""System tests for the wandb.sdk.sweeps.scheduler reference scheduler."""

from typing import Any
from unittest.mock import patch

from wandb.apis.public import SweepState
from wandb.sdk.sweeps.scheduler.scheduler import SchedulerOptions
from wandb.sdk.sweeps.scheduler.wandb import create_sweep_from_config

SWEEP_CONFIG_GRID_SINGLE: dict[str, Any] = {
    "name": "test-scheduler-grid-single",
    "method": "grid",
    "metric": {"name": "loss", "goal": "minimize"},
    "parameters": {"param1": {"values": [1]}},
    "scheduler": {"engine": "wandb"},
}


def test_loop_finishes_sweep_when_optimizer_should_terminate(user) -> None:
    """When the optimizer requests termination, loop() marks the sweep FINISHED."""
    project = "test-scheduler-terminate-sweep"

    scheduler = create_sweep_from_config(
        SWEEP_CONFIG_GRID_SINGLE,
        entity=user,
        project=project,
        options=SchedulerOptions(
            poll_interval_s=0.2,
            batch_size=1,
        ),
    )
    with patch.object(
        scheduler._optimizer,
        "should_terminate_sweep",
        return_value=True,
    ):
        scheduler.loop()

    assert scheduler.sweep_state() == SweepState.FINISHED
