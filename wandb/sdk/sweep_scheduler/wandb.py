"""Reference optimizer backed by the `sweeps` search algorithms."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from typing import Any

from wandb import Api, util
from wandb import sweep as wandb_sweep
from wandb.apis.public import Sweep
from wandb.sdk.launch.sweeps.scheduler import RunState
from wandb.sdk.sweep_scheduler.optimizer import (
    Optimizer,
    Run,
    RunConfig,
    RunEnriched,
    RunSuggestion,
    terminal_state,
)
from wandb.sdk.sweep_scheduler.scheduler import (
    Executor,
    InMemoryScheduler,
    Scheduler,
    scheduler_sweep_config,
)

sweeps = util.get_module(
    "sweeps",
    required="wandb[sweeps] is required to use the wandb sweep scheduler. "
    "Please run `pip install wandb[sweeps]`.",
)


def _to_sweeps_state(state: RunState) -> Any:
    """Map the scheduler's `RunState` onto the `sweeps` `RunState` enum."""
    try:
        return sweeps.RunState(state.value)
    except ValueError:
        return sweeps.RunState.pending


class WandbOptimizer(Optimizer):
    """`Optimizer` driven by the `sweeps` search algorithms.

    The `sweeps` search functions (``grid``/``random``/``bayes`` and the hyperband
    early-terminator) are *stateless*. Thus this class must maintain the full list
    of sweep runs in memory.
    """

    def __init__(self, search_config: dict[str, Any], sweep: Sweep):
        super().__init__(sweep)
        self._search_config = search_config
        # key: run id, value: the SweepRun we hold for it
        self._runs: dict[str, Any] = {}
        self._run_counter = 0

    def _new_run_id(self) -> str:
        run_id = f"{self._sweep.id}-{self._run_counter}"
        self._run_counter += 1
        return run_id

    def _record(self, run_id: str, data: RunEnriched) -> Any:
        """Create and store a SweepRun for `run_id` from `data`."""
        sweep_run = sweeps.SweepRun(
            name=run_id,
            # SweepRun.config is the wire form ({param: {"value": v}}); RunEnriched
            # carries the flat resolved config, so wrap it via RunConfig.
            config=RunConfig.from_values(data.config).model_dump(),
            state=_to_sweeps_state(data.state),
            summary_metrics=data.summary_metrics or {},
            history=list(data.history_metrics),
        )
        self._runs[run_id] = sweep_run
        return sweep_run

    def next_n_runs(self, n: int) -> Iterable[RunSuggestion]:
        suggested = sweeps.next_runs(
            self._search_config, list(self._runs.values()), n=n
        )
        suggestions: list[RunSuggestion] = []
        for sweep_run in suggested:
            # grid search returns None once the search space is exhausted.
            if sweep_run is None:
                continue
            run_id = self._new_run_id()
            sweep_run.name = run_id
            # Record it (state defaults to pending) so the next search call and
            # tell_run can find it.
            self._runs[run_id] = sweep_run
            # sweep_run.config is already the wire form RunConfig expects.
            suggestions.append(
                RunSuggestion(config=RunConfig(sweep_run.config), run_id=run_id)
            )
        return suggestions

    def tell_run(self, run_id: Any, data: RunEnriched) -> None:
        # "Save to memory" = update the SweepRun the search reads next time. Keep
        # the config we suggested — `data.config` may be empty (e.g. a reaped run)
        # — only the outcome (state, metrics, history) is new here.
        sweep_run = self._runs.get(run_id)
        if sweep_run is None:
            # Shouldn't happen: every run id we hand out is recorded first.
            return
        sweep_run.state = _to_sweeps_state(data.state)
        sweep_run.summary_metrics = data.summary_metrics or {}
        sweep_run.history = list(data.history_metrics)

    def prune_run(self, run_id: Any, data: RunEnriched) -> bool:
        # Hyperband early-termination, when the search config asks for it.
        if "early_terminate" not in self._search_config:
            return False
        try:
            to_stop = sweeps.stop_runs(self._search_config, list(self._runs.values()))
        except Exception:
            return False
        return any(run.name == run_id for run in to_stop)

    def tell_existing_finished_run(self, data: RunEnriched) -> None:
        # Warm-start: a terminal run that predates this optimizer. Add it to memory
        # so the search treats it as a completed sample.
        if terminal_state(data.state) is None:
            return
        self._record(self._new_run_id(), data)

    def tell_existing_active_run(self, data: Run) -> Any:
        # Adopt an in-flight run that predates this optimizer: store its config so
        # the search counts it as in flight. The next poll refreshes its metrics
        # via tell_run before any suggestion reads them.
        run_id = self._new_run_id()
        self._runs[run_id] = sweeps.SweepRun(
            name=run_id,
            config=RunConfig.from_values(data.config).model_dump(),
            state=_to_sweeps_state(data.state),
        )
        return run_id


# ---------------------------------------------------------------------------
# Public entry points.
#
# These free functions are the supported way to build a scheduler; callers
# should not instantiate `WandbOptimizer` directly. Each returns a scheduler
# whose `.loop()` drives the sweep.
# ---------------------------------------------------------------------------


def create_sweep_from_config(
    config: dict[str, Any],
    entity: str,
    project: str,
    *,
    poll_interval_s: float = 5.0,
    batch_size: int = 1,
    executor: Callable[[Sweep], Executor] | None = None,
) -> Scheduler:
    """Create a W&B sweep from `config` and attach a reference scheduler.

    `config` is an ordinary sweep config with a `method` of ``grid``/``random``/
    ``bayes``. The sweep is created with `scheduler_sweep_config` merged in
    (forcing `method: custom` so the server-side controller doesn't also drive
    it); the original `config` is kept locally to feed the `sweeps` search
    algorithms. `executor` is a factory taking the created sweep and returning the
    backend that schedules runs (defaults to enqueuing into the sweep's run queue).
    """
    search_config = copy.deepcopy(config)
    sweep_id = wandb_sweep(
        {**config, **scheduler_sweep_config}, entity=entity, project=project
    )
    sweep = Api().sweep(f"{entity}/{project}/{sweep_id}")
    optimizer = WandbOptimizer(search_config, sweep)
    return InMemoryScheduler(
        optimizer,
        sweep,
        poll_interval_s,
        batch_size,
        executor(sweep) if executor is not None else None,
    )


def resume_sweep(
    sweep: Sweep | str,
    search_config: dict[str, Any],
    *,
    poll_interval_s: float = 5.0,
    batch_size: int = 1,
    executor: Callable[[Sweep], Executor] | None = None,
) -> Scheduler:
    """Attach a reference scheduler to a sweep that already exists.

    `sweep` may be a `Sweep` or an ``"entity/project/sweep_id"`` path string. The
    sweep on the server was created with `method: custom`, so its real search
    `method`/`parameters` can't be read back off it; pass them in `search_config`.
    `executor` is a factory taking the resolved sweep and returning the backend
    that schedules runs (defaults to the W&B run queue).
    """
    resolved: Sweep = Api().sweep(sweep) if isinstance(sweep, str) else sweep
    optimizer = WandbOptimizer(search_config, resolved)
    return InMemoryScheduler(
        optimizer,
        resolved,
        poll_interval_s,
        batch_size,
        executor(resolved) if executor is not None else None,
    )
