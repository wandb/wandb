"""Basic ray-tune integration tests.

Based on:
    https://docs.wandb.ai/guides/integrations/ray-tune
    https://docs.ray.io/en/latest/tune/examples/tune-wandb.html
"""

import pathlib
import platform
import subprocess

import pytest


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="As of 2025/10/08, ray wheels for python>=3.13 are not available for Windows",
)
def test_tune_with_callback(wandb_backend_spy):
    """Example for using a WandbLoggerCallback with the function API."""
    train_script_path = pathlib.Path(__file__).parent / "tune_with_callback.py"
    subprocess.run(["python", str(train_script_path)], check=True)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        # we are doing a grid search over 3 values of alpha
        assert len(run_ids) == 3
        for run_id in run_ids:
            telemetry = snapshot.telemetry(run_id=run_id)
            assert 30 in telemetry["2"]  # import=ray
