"""End-to-end tests of the sweep scheduler across Python and wandb-core."""

from __future__ import annotations

import threading
import time
from typing import Any

import wandb
import yaml
from wandb.sdk import wandb_setup
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.ipc import SchedulerTaskExchange
from wandb.sdk.sweeps.scheduler.optimizer import Run, RunWithMetrics
from wandb.sdk.sweeps.scheduler.wandb import WandbOptimizer
from wandb.sdk.sweeps.sweep_info import SweepInfo

_INIT_TIMEOUT_SECONDS = 30
_POLL_INTERVAL_SECONDS = 0.2
_WAIT_TIMEOUT_SECONDS = 30

SWEEP_CONFIG = {
    "name": "sweep-scheduler-e2e",
    "method": "grid",
    "metric": {"name": "loss", "goal": "minimize"},
    "parameters": {"param1": {"values": [1, 2, 3]}},
    "scheduler": {"engine": "wandb"},
}


class _SpyOptimizer(WandbOptimizer):
    """A real WandbOptimizer, instrumented to observe its hook calls.

    The search logic is untouched; only the calls are recorded, so tests
    can wait for a specific real event (a warm-started run, a told
    update) instead of guessing at timing.
    """

    def __init__(self, sweep: SweepInfo) -> None:
        super().__init__(sweep)
        self.finished_told: list[RunWithMetrics] = []
        self.active_adopted: list[Run] = []
        self.told: list[tuple[Any, RunWithMetrics]] = []

    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        self.finished_told.append(data)
        return super().tell_existing_finished_run(data)

    def tell_existing_active_run(self, data: Run) -> Any:
        self.active_adopted.append(data)
        return super().tell_existing_active_run(data)

    def tell_run(self, run_id: Any, data: RunWithMetrics) -> None:
        self.told.append((run_id, data))
        return super().tell_run(run_id, data)


def _wait_until(predicate, *, timeout: float = _WAIT_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("timed out waiting for the scheduler")
        time.sleep(0.05)


def _start_scheduler(
    entity: str,
    project: str,
    sweep_id: str,
    *,
    batch_size: int = 1,
) -> tuple[_SpyOptimizer, str, threading.Thread, list]:
    """Start a real scheduler session against wandb-core, in a background thread.

    Returns the optimizer (to observe hook calls), the session id (to send
    a stop), the driving thread, and a one-element list that the thread
    fills in with the exchange's Done task once it finishes.
    """
    singleton = wandb_setup.singleton()
    service = singleton.ensure_service()

    async def init():
        handle = await service.init_sweep_scheduler(
            singleton.settings,
            entity=entity,
            project=project,
            sweep_id=sweep_id,
            batch_size=batch_size,
            poll_interval_seconds=_POLL_INTERVAL_SECONDS,
        )
        return await handle.wait_async(timeout=_INIT_TIMEOUT_SECONDS)

    init_response = singleton.asyncer.run(init)

    sweep = SweepInfo(
        id=sweep_id,
        name=init_response.display_name or sweep_id,
        entity=entity,
        project=project,
        config=yaml.safe_load(init_response.sweep_config) or {},
    )
    optimizer = _SpyOptimizer(sweep)
    exchange = SchedulerTaskExchange(service, init_response.session_id, optimizer)

    done_box: list = []

    def drive() -> None:
        done_box.append(singleton.asyncer.run(exchange.run))

    thread = threading.Thread(target=drive, daemon=True)
    thread.start()
    return optimizer, init_response.session_id, thread, done_box


def _stop_and_join(session_id: str, thread: threading.Thread, done_box: list):
    singleton = wandb_setup.singleton()
    service = singleton.ensure_service()

    async def stop():
        await service.stop_sweep_scheduler(session_id)

    singleton.asyncer.run(stop)
    thread.join(timeout=_WAIT_TIMEOUT_SECONDS)
    assert not thread.is_alive(), "the scheduler did not stop in time"
    return done_box[0]


def test_warm_start_adopts_prior_runs(user):
    """A sweep's pre-existing runs are handed to the optimizer on warm start."""
    entity, project = user, "sweep-scheduler-e2e-warm-start"
    sweep_id = wandb.sweep(SWEEP_CONFIG, entity=entity, project=project)

    with wandb.init(
        entity=entity, project=project, settings={"sweep_id": sweep_id}
    ) as run:
        run.log({"loss": 1.0})

    # Left running: the scheduler should adopt it as in-flight, not tell it.
    wandb.init(entity=entity, project=project, settings={"sweep_id": sweep_id})

    optimizer, session_id, thread, done_box = _start_scheduler(
        entity, project, sweep_id
    )
    try:
        _wait_until(lambda: optimizer.finished_told and optimizer.active_adopted)
        assert optimizer.finished_told[0].state == RunState.FINISHED
        assert optimizer.active_adopted[0].state == RunState.RUNNING
    finally:
        _stop_and_join(session_id, thread, done_box)


def test_generation_step_reports_a_finished_run(user):
    """A run the scheduler enqueues is told back to the optimizer once it finishes."""
    entity, project = user, "sweep-scheduler-e2e-finish"
    sweep_id = wandb.sweep(SWEEP_CONFIG, entity=entity, project=project)

    optimizer, session_id, thread, done_box = _start_scheduler(
        entity, project, sweep_id
    )
    try:
        # The scheduler enqueues one grid point (batch_size=1); wait for
        # the optimizer to learn the real wandb run id EnqueueRun minted.
        _wait_until(lambda: any(data.wandb_run_id for _, data in optimizer.told))
        wandb_run_id = next(
            data.wandb_run_id for _, data in optimizer.told if data.wandb_run_id
        )

        with wandb.init(
            entity=entity,
            project=project,
            id=wandb_run_id,
            resume="allow",
        ) as run:
            run.log({"loss": 0.5})

        _wait_until(
            lambda: any(
                data.wandb_run_id == wandb_run_id and data.state == RunState.FINISHED
                for _, data in optimizer.told
            )
        )
    finally:
        _stop_and_join(session_id, thread, done_box)


def test_stop_request_ends_the_exchange_with_shutdown(user):
    """Requesting a stop answers the outstanding poll with a shutdown Done task."""
    entity, project = user, "sweep-scheduler-e2e-stop"
    sweep_id = wandb.sweep(SWEEP_CONFIG, entity=entity, project=project)

    _optimizer, session_id, thread, done_box = _start_scheduler(
        entity, project, sweep_id
    )
    done = _stop_and_join(session_id, thread, done_box)

    assert done.reason == done.REASON_SHUTDOWN
