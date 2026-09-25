"""Unit tests of TrialResumer over a fake optimizer library."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Iterator, Mapping
from typing import Any

from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import Run, RunConfig, RunWithMetrics
from wandb.sdk.sweeps.scheduler.resumable import (
    SWEEP_LABEL,
    WANDB_RUN_ID_LABEL,
    ResumableTrials,
    TrialResumer,
)

from tests.unit_tests.test_sweep_scheduler import make_scheduler_grid_sweep

SWEEP = make_scheduler_grid_sweep()
SWEEP_PATH = f"{SWEEP.entity}/{SWEEP.project}/{SWEEP.id}"


class FakeTrial:
    def __init__(self, labels: dict[str, Any], running: bool, x: float):
        self.labels = labels
        self.running = running
        self.params = {"x": x}


class FakeTrials(ResumableTrials[FakeTrial]):
    """A library holding its trials by run id, as optimizer libraries do."""

    def __init__(self, trials: dict[int, FakeTrial]):
        self.trials = trials

    def existing(self) -> Iterator[FakeTrial]:
        yield from self.trials.values()

    def run_id(self, trial: FakeTrial) -> int:
        return next(i for i, t in self.trials.items() if t is trial)

    def labels(self, trial: FakeTrial) -> Mapping[str, Any]:
        return trial.labels

    def is_running(self, trial: FakeTrial) -> bool:
        return trial.running

    def label(self, run_id: Any, labels: dict[str, Any]) -> None:
        self.trials[run_id].labels.update(labels)

    def matches(self, run_id: Any, config: dict[str, Any]) -> bool:
        return self.trials[run_id].params == config

    def resume(self, run_id: Any) -> Any:
        return run_id

    def add_finished(self, data: RunWithMetrics) -> None:
        pass

    def adopt_new(self, data: Run) -> Any:
        return None


def test_the_index_keeps_no_trial_alive() -> None:
    """Only ids outlive the listing, so the library alone owns its trials."""
    library = FakeTrials(
        {
            0: FakeTrial({WANDB_RUN_ID_LABEL: "run-0"}, running=False, x=0.1),
            1: FakeTrial({WANDB_RUN_ID_LABEL: "run-1"}, running=True, x=0.2),
            2: FakeTrial({SWEEP_LABEL: SWEEP_PATH}, running=True, x=0.3),
        }
    )
    resumer = TrialResumer(SWEEP, library, tell_run=lambda run_id, data: None)
    unseen = Run(
        config=RunConfig.from_values({"x": 0.9}),
        state=RunState.RUNNING,
        wandb_run_id="run-9",
    )
    assert resumer.tell_existing_active_run(unseen) is None

    alive = [weakref.ref(trial) for trial in library.trials.values()]
    library.trials.clear()
    gc.collect()

    assert all(ref() is None for ref in alive)
