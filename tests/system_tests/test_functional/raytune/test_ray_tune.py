"""Basic ray-tune integration tests.

Based on:
    https://docs.wandb.ai/guides/integrations/ray-tune
    https://docs.ray.io/en/latest/tune/examples/tune-wandb.html
"""

import pathlib

import pytest


@pytest.mark.wandb_core_only
def test_tune_with_callback(user, relay_server, execute_script):
    """Example for using a WandbLoggerCallback with the function API."""

    train_script_path = pathlib.Path(__file__).parent / "tune_with_callback.py"

    with relay_server() as relay:
        execute_script(train_script_path)

    run_ids = relay.context.get_run_ids()
    # we are doing a grid search over 3 values of alpha
    assert len(run_ids) == 3
    for run_id in run_ids:
        telemetry = relay.context.get_run_telemetry(run_id)
        assert 30 in telemetry["2"]  # import=ray
