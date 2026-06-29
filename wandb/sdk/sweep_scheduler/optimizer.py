from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Any, List
from dataclasses import dataclass
from wandb import termerror, termlog, termwarn
from wandb.apis.public import Api, Sweep, SweepState
from wandb.apis.internal import InternalApi
import logging
import time

from wandb.sdk.launch.sweeps.scheduler import RunState

_logger = logging.getLogger(__name__)

scheduler_sweep_config = {
    "method": "custom",
    "controller": {"type": "scheduler"},
}

@dataclass
class RunSuggestion:
    config: dict
    run_id: str

@dataclass
class RunData:
    config: dict
    state: RunState
    wandb_run_id: str
    summary_metrics: dict[str, Any]
    history_metrics: List[dict[str, Any]]


def terminal_state(state: RunState) -> RunState | None:
    """Return `state` if the run has stopped (is terminal), else None.

    In-flight states (running/pending/preempting/preempted/unknown) return None.
    Used to decide whether a run's result can be reported to the optimizer.
    """
    if state in (
        RunState.FINISHED,
        RunState.FAILED,
        RunState.CRASHED,
        RunState.KILLED,
    ):
        return state
    return None


class Executor(ABC):
    @abstractmethod
    def schedule(self, suggestion: RunSuggestion) -> str:
        """Start or queue a run for `suggestion`; return its W&B run id."""
        ...

    def reap(self, run_ids: Iterable[str]) -> set[str]:
        """Return the subset of `run_ids` whose backend jobs are no longer alive.

        The optimizer calls this each poll with the runs W&B still considers
        in-flight, to catch jobs that died before `wandb.init` ran (rejected,
        preempted, crashed at startup) and left their W&B run stuck PENDING.
        Returned ids are finalized as failed and dropped from the in-flight set,
        freeing capacity.

        Must not mutate `run_ids`. The default returns an empty set: for the queue
        / W&B-agent backend the W&B run state is authoritative and the agent owns
        the run lifecycle, so there is nothing extra to reconcile. Direct backends
        (SLURM, Volcano, ...) override this to consult their scheduler (squeue /
        sacct, the K8s API, ...).
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
        # The agent reads each param as {"value": <v>} and the server forwards the
        # enqueued config to it verbatim, so wrap the flat suggestion config.
        run_config = {
            param: {"value": value}
            for param, value in suggestion.config.items()
        }
        return self._sweep.enqueue_run(run_config)


class StatefulOptimizer:
    """Interact with an external optimizer that supports an
    ask-tell interface."""
    
    def __init__(self, sweep: Sweep,
        poll_interval_s: float,
        batch_size: int,
        executor: Executor | None = None):
        """sweep: the sweep to interact with
        poll_interval_s: the interval in seconds to poll the sweep for new runs
        batch_size: the number of runs to suggest at a time
        executor: backend that schedules each suggested run and returns its W&B
            run id. Defaults to enqueuing into the sweep's run queue.
        """
        self._sweep = sweep
        self._poll_interval_s = poll_interval_s
        self._batch_size = batch_size
        self._api = Api()
        self._executor = executor or WBAgentExecutor(sweep)
        # Key: wandb run id, Value: external optimizer run id
        self._run_id_mapping: dict[str, Any] = {}
        # Runs we've enqueued that haven't reached a terminal state yet. Bounded
        # by `batch_size`, so it doubles as the in-flight count and as the set we
        # filter the runs query by.
        self._unreported_runs: set[str] = set()

    def _tell_existing_finished_runs(self) -> None:
        """Report every run already in the sweep to the optimizer.

        Lets a resumed optimizer account for prior results before the loop starts
        enqueuing new runs. Uses a lazy query so each run's config/summary is
        fetched via a per-run full load on attribute access. The bulk
        (`lazy=False`) list query does not reliably populate `summaryMetrics`,
        """
        existing = self._api.runs(
            path=f"{self._sweep.entity}/{self._sweep.project}",
            filters={"sweep": self._sweep.id},
        )
        for run in existing:
            # Warm-start must never block the loop from proposing new runs. 
            # Errors ingesting existing runs must be skipped with a warning.
            try:
                data = RunData(
                    config=run.config,
                    wandb_run_id=run.id,
                    summary_metrics=run.summary_metrics,
                    history_metrics=[],
                    state=RunState(run.state),
                )
                if terminal_state(data.state) is not None:
                    self.tell_existing_finished_run(data)
                elif data.state in (RunState.RUNNING, RunState.PENDING):
                    # Still in flight: adopt it so the loop keeps driving it and it
                    # counts toward the in-flight cap, instead of being re-proposed.
                    optimizer_run_id = self.tell_existing_active_run(data)
                    if optimizer_run_id is not None:
                        self._track_run(run.id, optimizer_run_id)
            except Exception as e:
                termwarn(
                    f"Skipping existing run {run.id} while warm-starting sweep "
                    f"{self._sweep.name}: {e}"
                )

    def _fetch_active_runs(self) -> Iterable[Any]:
        """Re-query our in-flight runs with fresh state/metrics."""
        if not self._unreported_runs:
            return []
        # `Api.runs` caches results by (path, filters); with a stable in-flight set
        # the filter is identical every poll, so without flushing we'd get back the
        # same cached Run objects with stale state/history forever — runs would
        # never look terminal, never drain, and capacity would stay pinned. Flush
        # so each poll re-queries fresh.
        self._api.flush()
        return self._api.runs(
            path=f"{self._sweep.entity}/{self._sweep.project}",
            filters={
                "sweep": self._sweep.id,
                "name": {"$in": list(self._unreported_runs)},
            },
        )

    def next_n_runs(self, n: int) -> Iterable[RunSuggestion]:
        return []
    def tell_run(self, run_id: Any, data: RunData) -> None:
        pass

    def tell_existing_finished_run(self, data: RunData) -> None:
        """Report a *terminal* run that already existed in the sweep at startup.

        Unlike `tell_run`, there is no optimizer-side run id because the run was
        not produced by this optimizer's `next_n_runs`. Override to warm-start
        from prior results; the default is a no-op.
        """
        pass

    def tell_existing_active_run(self, data: RunData) -> Any:
        """Adopt an *in-flight* (RUNNING/PENDING) run that already existed in the
        sweep at startup.

        Recreate whatever optimizer-side state is needed to keep driving the run
        (so the loop can `tell_run`/`prune_run` it when it next polls) and return
        the optimizer-side run id to track it by. Return None to skip adoption;
        the default is a no-op.
        """
        return None

    def _track_run(self, wandb_run_id: str, optimizer_run_id: Any) -> None:
        """Record an in-flight run: within Optimizer state, irregardless of
        the external optimizer's perspective."""
        self._run_id_mapping[wandb_run_id] = optimizer_run_id
        self._unreported_runs.add(wandb_run_id)

    def _reap_dead_runs(self) -> None:
        """Fail and drain in-flight runs whose backend job is no longer alive.

        A direct executor (e.g. SLURM/Volcano) may schedule a job that never
        reaches `wandb.init` (rejected, preempted, crashed at startup), leaving
        its W&B run stuck PENDING and pinned in-flight forever. Ask the executor
        which tracked runs it can no longer find and finalize them as failed so
        the optimizer learns the outcome and capacity frees up. No-op for the
        default queue/agent executor (its `reap` returns nothing).
        """
        if not self._unreported_runs:
            return
        for run_id in self._executor.reap(self._unreported_runs):
            optimizer_run_id = self._run_id_mapping.get(run_id)
            if optimizer_run_id is None:
                continue
            termwarn(
                f"Run {run_id} in sweep {self._sweep.name} is no longer alive at "
                f"the executor but never reached a terminal W&B state; marking it "
                f"failed."
            )
            data = RunData(
                config={},
                state=RunState.FAILED,
                wandb_run_id=run_id,
                summary_metrics={},
                history_metrics=[],
            )
            try:
                self.tell_run(optimizer_run_id, data)
            except Exception as e:
                termerror(
                    f"Error telling reaped run {run_id} in sweep "
                    f"{self._sweep.name}: {e}"
                )
            self._unreported_runs.discard(run_id)

    def metric_value(self, metrics: dict[str, Any]) -> Any:
        """Return the objective value for the sweep's configured metric.

        `metrics` is a metrics dict — either `RunData.summary_metrics` or a single
        row from `RunData.history_metrics`. Returns None when the metric is absent
        from the given dict (e.g. a history step that didn't log it).
        """

        return metrics.get(self.metric_key())

    def metric_key(self) -> str:
        metric = self._sweep.config.get("metric")
        if not metric or "name" not in metric:
            raise ValueError(
                "Sweep config has no metric; cannot determine the objective value."
            )
        return metric["name"]

    @property
    def sweep_name(self) -> str:
        return self._sweep.name

    def prune_run(self, run_id: Any, data: RunData) -> bool:
        """Return True if the run should be pruned.

        `data` is the RunData for the run.
        """
        return False

    def loop(self) -> None:
        # Warm-start the optimizer with runs that already exist in the sweep
        # (e.g. from a previous scheduler instance) before enqueuing new ones.
        self._tell_existing_finished_runs()
        while self._sweep.state in [SweepState.RUNNING, SweepState.PENDING]:
            # Poll at the end of every iteration via `finally` so that the
            # `continue` paths below still wait before re-checking sweep state.
            try:
                for run in self._fetch_active_runs():
                    if run.id not in self._run_id_mapping:
                        # A run we didn't enqueue (e.g. pre-existing); ignore it.
                        continue

                    data = RunData(
                        config=run.config,
                        wandb_run_id=run.id,
                        summary_metrics=run.summary_metrics,
                        history_metrics=run.history(keys=[self.metric_key()], samples=20, pandas=False),
                        state=RunState(run.state)
                    )

                    if self.metric_value(data.summary_metrics) is None and data.state == RunState.FINISHED:
                        termwarn(f"Run {run.id} in sweep {self._sweep.name} has no metric value")
                        data.state = RunState.FAILED

                    try:
                        self.tell_run(self._run_id_mapping[run.id], data)
                    except Exception as e:
                        termerror(f"Error telling run {run.id} in sweep {self._sweep.name}: {e}")
                        raise e

                    if data.state not in [RunState.RUNNING, RunState.PENDING]:
                        self._unreported_runs.discard(run.id)
                    elif self.prune_run(self._run_id_mapping[run.id], data):
                        termlog(
                            f"Pruning run {run.id} (optimizer run "
                            f"{self._run_id_mapping[run.id]}) in sweep {self._sweep.name}"
                        )
                        if InternalApi().stop_run(run.storage_id):
                            self._unreported_runs.discard(run.id)

                # Reconcile against the executor's backend: drop runs whose job
                # died before reporting to W&B (otherwise they'd pin capacity).
                self._reap_dead_runs()

                # Keep at most `batch_size` runs in flight. `_unreported_runs` is
                # populated on enqueue/adoption and drained above when a run goes
                # terminal, so it is the in-flight count. Unlike a backend query it
                # already includes just-enqueued runs (no lag) and can't be skewed
                # by run-state filter quirks or by other sweeps' runs.
                n_to_enqueue = self._batch_size - len(self._unreported_runs)
                if n_to_enqueue <= 0:
                    continue

                suggestions = self.next_n_runs(n_to_enqueue)
                for suggestion in suggestions:
                    wandb_run_id = self._executor.schedule(suggestion)
                    self._track_run(wandb_run_id, suggestion.run_id)
                    termlog(
                        f"Scheduled run {wandb_run_id} (optimizer run "
                        f"{suggestion.run_id}) in sweep {self._sweep.name} "
                        f"with config {suggestion.config}"
                    )
            except Exception as e:
                termerror(f"Error in optimizer loop for sweep {self._sweep.name}: {e}")
                raise e
            finally:
                time.sleep(self._poll_interval_s)

        termerror(f"Sweep {self._sweep.name} has exited with state {self._sweep.state}")

    def exit(self) -> None:
        self._sweep.finish()

    def __del__(self) -> None:
        self.exit()
