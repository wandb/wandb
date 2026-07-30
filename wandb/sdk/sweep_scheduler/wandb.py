"""Reference optimizer backed by the `sweeps` search algorithms."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from wandb import util
from wandb.apis.public import Sweep
from wandb.sdk.launch.sweeps.scheduler import RunState
from wandb.sdk.sweep_scheduler.optimizer import (
    ConfigValue,
    Optimizer,
    Run,
    RunConfig,
    RunEnriched,
    RunSuggestion,
    is_terminal_state,
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

    The `sweeps` search functions (`grid`/`random`/`bayes` and the hyperband
    early-terminator) are stateless, so this class keeps the full list of sweep
    runs in memory.
    """

    def __init__(self, sweep: Sweep):
        super().__init__(sweep)
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
            config=data.config.wire_dict(),
            state=_to_sweeps_state(data.state),
            summary_metrics=data.summary_metrics or {},
            history=list(data.history_metrics),
        )
        self._runs[run_id] = sweep_run
        return sweep_run

    def next_n_runs(self, n: int) -> Sequence[RunSuggestion]:
        """Ask the `sweeps` search for up to `n` new runs.

        Args:
            n: The maximum number of runs to propose.
        """
        suggested = sweeps.next_runs(self._sweep.config, list(self._runs.values()), n=n)
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
                RunSuggestion(
                    config=RunConfig(
                        {
                            name: ConfigValue(**param)
                            for name, param in sweep_run.config.items()
                        }
                    ),
                    run_id=run_id,
                )
            )
        return suggestions

    def tell_run(self, run_id: Any, data: RunEnriched) -> None:
        """Record a run's latest outcome for the next search call to read.

        Args:
            run_id: The run id this optimizer handed out.
            data: The run's current state, summary metrics and history.

        Raises:
            ValueError: If `run_id` was never proposed by this optimizer.
        """
        # "Save to memory" = update the SweepRun the search reads next time.
        # Keep the config we suggested — `data.config` may be empty (e.g. a
        # reaped run) — only the outcome (state, metrics, history) is new here.
        sweep_run = self._runs.get(run_id)
        if sweep_run is None:
            raise ValueError(f"Run {run_id} not found")
        sweep_run.state = _to_sweeps_state(data.state)
        sweep_run.summary_metrics = data.summary_metrics or {}
        sweep_run.history = list(data.history_metrics)

    def prune_run(self, run_id: Any, data: RunEnriched) -> bool:
        """Return True if hyperband says the run should stop early.

        Always False unless the sweep config has an `early_terminate` block.

        Args:
            run_id: The run id this optimizer handed out.
            data: The run's current state, summary metrics and history.
        """
        if "early_terminate" not in self._sweep.config:
            return False
        try:
            to_stop = sweeps.stop_runs(self._sweep.config, list(self._runs.values()))
        except Exception:
            return False
        return any(run.name == run_id for run in to_stop)

    def should_terminate_sweep(self) -> bool:
        """Sweeps library does not implement this, so we return False."""
        return False

    def tell_existing_finished_run(self, data: RunEnriched) -> None:
        """Add a terminal run that predates this optimizer to its memory.

        The search then treats it as a completed sample. Non-terminal runs are
        ignored.

        Args:
            data: The existing run's state, summary metrics and history.
        """
        if not is_terminal_state(data.state):
            return
        self._record(self._new_run_id(), data)

    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run that predates this optimizer.

        Its config is stored so the search counts it as in flight; the next poll
        refreshes its metrics via `tell_run` before any suggestion reads them.

        Args:
            data: The existing run's config and state.

        Returns:
            The optimizer run id to track the run by.
        """
        run_id = self._new_run_id()
        self._runs[run_id] = sweeps.SweepRun(
            name=run_id,
            config=data.config.wire_dict(),
            state=_to_sweeps_state(data.state),
        )
        return run_id
