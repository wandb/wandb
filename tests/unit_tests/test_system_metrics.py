"""Checks that wandb-symon, the system metrics sidecar, streams samples to a run."""

import pathlib
import shutil
import time

import pytest
import wandb

pytestmark = pytest.mark.skipif(
    shutil.which("wandb-symon", path=str(pathlib.Path(wandb.__file__).parent / "bin"))
    is None,
    reason="wandb was built without wandb-symon",
)


def test_system_metrics_are_sampled(monkeypatch):
    monkeypatch.setenv("WANDB_MODE", "offline")
    monkeypatch.setenv("WANDB_X_STATS_SAMPLING_INTERVAL", "0.1")
    monkeypatch.setenv("WANDB_X_STATS_BUFFER_SIZE", "100")

    with wandb.init() as run:
        while len(run._system_metrics.get("memory_percent", [])) < 2:
            time.sleep(0.1)


def test_system_metrics_resume_after_pause(monkeypatch):
    """Notebooks pause the monitor after each cell and resume it before the next."""
    monkeypatch.setenv("WANDB_MODE", "offline")
    monkeypatch.setenv("WANDB_X_STATS_SAMPLING_INTERVAL", "0.1")
    monkeypatch.setenv("WANDB_X_STATS_BUFFER_SIZE", "100")

    with wandb.init() as run:
        while "memory_percent" not in run._system_metrics:
            time.sleep(0.1)

        run._interface.publish_pause()
        while True:
            last = run._system_metrics["memory_percent"][-1]
            time.sleep(1)
            if run._system_metrics["memory_percent"][-1] == last:
                break

        run._interface.publish_resume()
        while run._system_metrics["memory_percent"][-1] == last:
            time.sleep(0.1)
