from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, MutableMapping
from typing import Any, TypeVar

from wandb import termerror, termlog, termwarn
from wandb.apis.internal import InternalApi
from wandb.apis.public import Api, Sweep, SweepState
from wandb.sdk.launch.sweeps.scheduler import RunState
from wandb.sdk.sweep_scheduler.optimizer import (
    Optimizer,
    Run,
    RunEnriched,
    RunSuggestion,
    terminal_state,
)

scheduler_sweep_config = {
    "method": "custom",
    "controller": {"type": "scheduler"},
}

_RunT = TypeVar("_RunT", bound=Run)
_T = TypeVar("_T")

# Run states that can be adopted and kept driving at warm-start.
_ADOPTABLE_STATES = [RunState.RUNNING.value, RunState.PENDING.value]
# Terminal states, derived from `terminal_state` so the two stay in sync.
_TERMINAL_STATES = [s.value for s in RunState if terminal_state(s) is not None]

_WARM_START_PAGE_SIZE = 200


def _batched(iterable: Iterable[_T], size: int) -> Iterator[list[_T]]:
    """Yield successive lists of at most `size` items from `iterable`.

    (``itertools.batched`` would do this, but it's only available on Python 3.12+.)
    """
    batch: list[_T] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


class Executor(ABC):
    @abstractmethod
    def schedule(self, suggestion: RunSuggestion) -> str:
        """Start or queue a run for `suggestion`; return its W&B run id."""
        ...

    def reap(self, run_ids: Iterable[str]) -> set[str]:
        """Return the subset of `run_ids` whose backend jobs are no longer alive.

        The scheduler calls this each poll with the runs W&B still considers
        in-flight, to catch jobs that died before `wandb.init` ran (rejected,
        preempted, crashed at startup) and left their W&B run stuck PENDING.
        Returned ids are finalized as failed and dropped from the in-flight set,
        freeing capacity.
        """
        return set()


class WBAgentExecutor(Executor):
    """Default executor: enqueue the run into the W&B sweep's run queue.

    A W&B agent (`wandb agent <sweep>`) pulls the queued run and executes it. The
    server creates the run PENDING, associated with the sweep, and returns its id.
    """

    def __init__(self, sweep: Sweep):
        self._sweep = sweep

    def schedule(self, suggestion: RunSuggestion) -> str:
        return self._sweep.enqueue_run(suggestion.config.model_dump())


class Scheduler(ABC):
    """Drive an `Optimizer` against a sweep, keeping `batch_size` runs in flight.

    Poll runs, tell the optimizer their results, and enqueue its suggestions.
    Subclasses implement the hooks below to choose where in-flight state lives
    (memory/sqlite/postgres) and how runs are observed (`Api.runs` polling today,
    event sourcing later). See `InMemoryScheduler` for the default.
    """

    def __init__(
        self,
        optimizer: Optimizer,
        sweep: Sweep,
        poll_interval_s: float,
        batch_size: int,
        executor: Executor | None = None,
    ):
        self._optimizer = optimizer
        self._sweep = sweep
        self._poll_interval_s = poll_interval_s
        self._batch_size = batch_size
        self._executor = executor or WBAgentExecutor(sweep)

    @abstractmethod
    def in_flight_runs(self) -> MutableMapping[str, Any]:
        """The live, mutable {wandb_run_id: optimizer_run_id} map of in-flight runs."""
        ...
    
    @abstractmethod
    def pop_in_flight_run(self, wandb_run_id: str) -> Any:
        """Remove a run from the in-flight set."""
        ...

    @abstractmethod
    def fetch_existing_finished_runs(self) -> Iterable[RunEnriched]:
        """Terminal runs already in the sweep, with their summary metrics."""
        ...

    @abstractmethod
    def fetch_existing_unfinished_runs(self) -> Iterable[Run]:
        """In-flight runs already in the sweep, light (no metrics) — to adopt."""
        ...

    @abstractmethod
    def fetch_active_runs(self) -> Iterable[RunEnriched]:
        """The tracked in-flight runs, with fresh state/metrics and history."""
        ...

    @abstractmethod
    def sweep_state(self) -> SweepState:
        """The sweep's current state; the loop runs while RUNNING/PENDING."""
        ...

    @abstractmethod
    def stop_run(self, wandb_run_id: str) -> bool:
        """Request that a run stop early; return True if the stop was accepted."""
        ...

    def loop(self) -> None:
        # Warm-start the optimizer with runs that already exist in the sweep
        # (e.g. from a previous scheduler instance) before enqueuing new ones.
        self._warm_start()
        while self.sweep_state() in [SweepState.RUNNING, SweepState.PENDING]:
            # Poll at the end of every iteration via `finally` so that the early
            # returns below still wait before re-checking sweep state.
            try:
                self._poll_active_runs()
                # Reconcile against the executor's backend: drop runs whose job
                # died before reporting to W&B (otherwise they'd pin capacity).
                self._reap_dead_runs()
                self._enqueue_suggestions()
            except Exception as e:
                termerror(f"Error in scheduler loop for sweep {self._sweep.name}: {e}")
                raise
            finally:
                time.sleep(self._poll_interval_s)

        termerror(
            f"Sweep {self._sweep.name} has exited with state {self.sweep_state()}"
        )

    def _warm_start(self) -> None:
        # Warm-start must never block the loop from proposing new runs; errors
        # ingesting an existing run are skipped with a warning. Replay completed
        # results first, then adopt the in-flight runs. Both queries are paginated
        # and told to the optimizer in bounded batches so a sweep with many prior
        # runs is never materialized all at once.
        for batch in _batched(
            self.fetch_existing_finished_runs(), _WARM_START_PAGE_SIZE
        ):
            for run in batch:
                try:
                    self._optimizer.tell_existing_finished_run(run)
                except Exception as e:
                    termwarn(
                        f"Skipping finished run {run.wandb_run_id} while warm-starting "
                        f"sweep {self._sweep.name}: {e}"
                    )
        in_flight = self.in_flight_runs()
        for batch in _batched(
            self.fetch_existing_unfinished_runs(), _WARM_START_PAGE_SIZE
        ):
            for run in batch:
                # Adopt it so the loop keeps driving it and it counts toward the
                # in-flight cap, instead of being re-proposed.
                try:
                    optimizer_run_id = self._optimizer.tell_existing_active_run(run)
                    if optimizer_run_id is not None:
                        in_flight[run.wandb_run_id] = optimizer_run_id
                except Exception as e:
                    termwarn(
                        f"Skipping unfinished run {run.wandb_run_id} while "
                        f"warm-starting sweep {self._sweep.name}: {e}"
                    )

    def _poll_active_runs(self) -> None:
        in_flight = self.in_flight_runs()
        active = self.fetch_active_runs()
        for data in active:
            wandb_run_id = data.wandb_run_id
            if wandb_run_id not in in_flight:
                # A run we didn't enqueue (e.g. pre-existing); ignore it.
                continue
            optimizer_run_id = in_flight[wandb_run_id]

            if (
                self._optimizer.metric_value(data.summary_metrics) is None
                and data.state == RunState.FINISHED
            ):
                termwarn(
                    f"Run {wandb_run_id} in sweep {self._sweep.name} has no metric value"
                )
                data.state = RunState.FAILED

            try:
                self._optimizer.tell_run(optimizer_run_id, data)
            except Exception as e:
                termerror(
                    f"Error telling run {wandb_run_id} in sweep {self._sweep.name}: {e}"
                )
                raise

            if data.state not in [RunState.RUNNING, RunState.PENDING]:
                self.pop_in_flight_run(wandb_run_id)
            elif self._optimizer.prune_run(optimizer_run_id, data):
                termlog(
                    f"Pruning run {wandb_run_id} (optimizer run {optimizer_run_id}) "
                    f"in sweep {self._sweep.name}"
                )
                if self.stop_run(wandb_run_id):
                    self.pop_in_flight_run(wandb_run_id)
        self._reap_deleted_runs(active)

    def _reap_deleted_runs(self, active: Iterable[Run]) -> None:
        active_set = set(run.wandb_run_id for run in active)
        runs = list(self.in_flight_runs().keys())
        for wandb_run_id in runs:
            if wandb_run_id not in active_set:
                self._optimizer.tell_run(self.in_flight_runs()[wandb_run_id], RunEnriched(
                    config={},
                    state=RunState.FAILED,
                    wandb_run_id=wandb_run_id,
                    summary_metrics={},
                    history_metrics=[],
                ))
                self.pop_in_flight_run(wandb_run_id)

    def _reap_dead_runs(self) -> None:
        """Fail and drain in-flight runs whose backend job is no longer alive.

        A direct executor (e.g. SLURM/Volcano) may schedule a job that never
        reaches `wandb.init` (rejected, preempted, crashed at startup), leaving
        its W&B run stuck PENDING and pinned in-flight forever. Ask the executor
        which tracked runs it can no longer find and finalize them as failed so
        the optimizer learns the outcome and capacity frees up. No-op for the
        default queue/agent executor (its `reap` returns nothing).
        """
        in_flight = self.in_flight_runs()
        if not in_flight:
            return
        for run_id in self._executor.reap(set(in_flight)):
            optimizer_run_id = in_flight.get(run_id)
            if optimizer_run_id is None:
                continue
            termwarn(
                f"Run {run_id} in sweep {self._sweep.name} is no longer alive at "
                f"the executor but never reached a terminal W&B state; marking it "
                f"failed."
            )
            data = RunEnriched(
                config={},
                state=RunState.FAILED,
                wandb_run_id=run_id,
                summary_metrics={},
                history_metrics=[],
            )
            try:
                self._optimizer.tell_run(optimizer_run_id, data)
            except Exception as e:
                termerror(
                    f"Error telling reaped run {run_id} in sweep "
                    f"{self._sweep.name}: {e}"
                )
            in_flight.pop(run_id, None)

    def _enqueue_suggestions(self) -> None:
        # Keep at most `batch_size` runs in flight. `in_flight_runs` is populated
        # on enqueue/adoption and drained as runs go terminal, so its size is the
        # in-flight count. Unlike a backend query it already includes just-enqueued
        # runs (no lag) and can't be skewed by run-state filter quirks.
        in_flight = self.in_flight_runs()
        n_to_enqueue = self._batch_size - len(in_flight)
        if n_to_enqueue <= 0:
            return
        for suggestion in self._optimizer.next_n_runs(n_to_enqueue):
            wandb_run_id = self._executor.schedule(suggestion)
            in_flight[wandb_run_id] = suggestion.run_id
            termlog(
                f"Scheduled run {wandb_run_id} (optimizer run {suggestion.run_id}) "
                f"in sweep {self._sweep.name} with config {suggestion.config.values}"
            )

    def exit(self) -> None:
        self._sweep.finish()

    def __del__(self) -> None:
        self.exit()


class InMemoryScheduler(Scheduler):
    """Track in-flight runs in process memory and observe runs by polling `Api.runs`."""

    def __init__(
        self,
        optimizer: Optimizer,
        sweep: Sweep,
        poll_interval_s: float,
        batch_size: int,
        executor: Executor | None = None,
    ):
        super().__init__(optimizer, sweep, poll_interval_s, batch_size, executor)
        self._api = Api()
        # Key: wandb run id, Value: optimizer run id
        self._in_flight: dict[str, Any] = {}
        # wandb run id -> storage id, captured on fetch so stop_run can target it.
        self._storage_ids: dict[str, str] = {}

    def in_flight_runs(self) -> MutableMapping[str, Any]:
        return self._in_flight

    def pop_in_flight_run(self, wandb_run_id: str) -> Any:
        return self._in_flight.pop(wandb_run_id, None)

    def fetch_existing_finished_runs(self) -> Iterable[RunEnriched]:
        runs = self._sweep_runs(
            {"state": {"$in": _TERMINAL_STATES}}, per_page=_WARM_START_PAGE_SIZE
        )
        return self._build_runs(
            runs,
            lambda run: RunEnriched(
                config=run.config,
                state=RunState(run.state),
                wandb_run_id=run.id,
                summary_metrics=run.summary_metrics,
                history_metrics=[],
            ),
        )

    def fetch_existing_unfinished_runs(self) -> Iterable[Run]:
        runs = self._sweep_runs(
            {"state": {"$in": _ADOPTABLE_STATES}}, per_page=_WARM_START_PAGE_SIZE
        )
        return self._build_runs(
            runs,
            lambda run: Run(
                config=run.config,
                state=RunState(run.state),
                wandb_run_id=run.id,
            ),
        )

    def fetch_active_runs(self) -> Iterable[RunEnriched]:
        if not self._in_flight:
            return []
        # `Api.runs` caches results by (path, filters); with a stable in-flight set
        # the filter is identical every poll, so without flushing we'd get back the
        # same cached Run objects with stale state/history forever — runs would
        # never look terminal, never drain, and capacity would stay pinned. Flush
        # so each poll re-queries fresh.
        self._api.flush()
        runs = self._sweep_runs({"name": {"$in": list(self._in_flight)}})
        self._storage_ids = {}
        active = []
        for run in runs:
            self._storage_ids[run.id] = run.storage_id
            active.append(
                RunEnriched(
                    config=run.config,
                    state=RunState(run.state),
                    wandb_run_id=run.id,
                    summary_metrics=run.summary_metrics,
                    history_metrics=run.history(
                        keys=[self._optimizer.metric_key()], samples=20, pandas=False
                    ),
                )
            )
        return active

    def sweep_state(self) -> SweepState:
        return self._sweep.state

    def stop_run(self, wandb_run_id: str) -> bool:
        storage_id = self._storage_ids.get(wandb_run_id)
        if storage_id is None:
            return False
        return bool(InternalApi().stop_run(storage_id))

    def _sweep_runs(self, filters: dict[str, Any], per_page: int = 50) -> Iterable[Any]:
        return self._api.runs(
            path=f"{self._sweep.entity}/{self._sweep.project}",
            filters={"sweep": self._sweep.id, **filters},
            per_page=per_page,
            lazy=False,
        )

    def _build_runs(
        self, runs: Iterable[Any], builder: Callable[[Any], _RunT]
    ) -> Iterator[_RunT]:
        # Lazily yield built runs as the paginated query advances, so warm-start can
        # process them a page at a time rather than holding every run in memory.
        for run in runs:
            # A single unreadable run must not abort warm-starting the rest.
            try:
                built = builder(run)
            except Exception as e:
                termwarn(
                    f"Skipping run {run.id} while warm-starting sweep "
                    f"{self._sweep.name}: {e}"
                )
                continue
            yield built
