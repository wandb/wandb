"""Reference optimizer backed by the `sweeps` search algorithms."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from typing_extensions import override

from wandb import sweep as wandb_sweep
from wandb import util
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.client import SchedulerOptions, run_scheduler
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    Run,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
    is_terminal_state,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

if TYPE_CHECKING:
    import sweeps
else:
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

    The `sweeps` search functions are stateless, so this class keeps the full
    list of sweep runs in memory.
    """

    @override
    def __init__(self, sweep: SweepInfo):
        super().__init__(sweep)
        self._runs: dict[str, sweeps.SweepRun] = {}
        self._run_counter = 0

    @override
    def validate_sweep_objective(self) -> None:
        """No-op: the sweep config is the only objective this optimizer reads.

        There is no external study or experiment that could disagree with it.
        """
        return None

    def _new_run_id(self) -> str:
        run_id = f"{self._sweep.id}-{self._run_counter}"
        self._run_counter += 1
        return run_id

    def _to_sweep_run(self, run_id: str, data: RunWithMetrics) -> Any:
        sweep_run = sweeps.SweepRun(
            name=run_id,
            config=data.config.wire_dict(),
            state=_to_sweeps_state(data.state),
        )
        sweep_run.summary_metrics = data.summary_metrics or {}
        sweep_run.history = list(data.history_metrics)
        return sweep_run

    def _record(self, run_id: str, data: RunWithMetrics) -> Any:
        sweep_run = self._to_sweep_run(run_id, data)
        self._runs[run_id] = sweep_run
        return sweep_run

    def _sweep_runs_for_stop_runs(
        self, run_ids: Sequence[str], runs: Sequence[RunWithMetrics]
    ) -> list[Any]:
        """Merge in-memory runs with the scheduler's latest poll snapshot."""
        sweep_runs_by_name = {run.name: run for run in self._runs.values()}
        for run_id, data in zip(run_ids, runs, strict=True):
            sweep_runs_by_name[run_id] = self._to_sweep_run(run_id, data)
        return list(sweep_runs_by_name.values())

    @override
    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion]:
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
            # State defaults to pending, so the next search call and tell_run
            # can find it.
            self._runs[run_id] = sweep_run
            # Unwrap the wire form `sweeps` returns into a flat mapping.
            suggestions.append(
                RunSuggestion(
                    config=RunConfig.from_values(
                        {
                            name: param["value"]
                            for name, param in sweep_run.config.items()
                        }
                    ),
                    run_id=run_id,
                )
            )
        return suggestions

    @override
    def tell_run(self, run_id: Any, data: RunWithMetrics) -> None:
        """Record a run's latest outcome for the next search call to read.

        Args:
            run_id: The run id this optimizer handed out.
            data: The run's current state, summary metrics and history.

        Raises:
            ValueError: If `run_id` was never proposed by this optimizer.
        """
        # Keep the config we suggested: `data.config` may be empty for a
        # reaped run.
        sweep_run = self._runs.get(run_id)
        if sweep_run is None:
            raise ValueError(f"Run {run_id} not found")
        sweep_run.state = _to_sweeps_state(data.state)
        sweep_run.summary_metrics = data.summary_metrics or {}
        sweep_run.history = list(data.history_metrics)

    @override
    def forget_run(self, run_id: Any) -> None:
        """Drop a run that will never start from the search's memory.

        Deleting it, rather than recording a failure, lets grid search
        propose the same point again.

        Args:
            run_id: The run id this optimizer handed out.
        """
        self._runs.pop(run_id, None)

    @override
    def prune_runs(
        self, run_ids: Sequence[str], runs: Sequence[RunWithMetrics]
    ) -> Sequence[str]:
        """Return the runs hyperband says should stop early.

        Returns nothing unless the sweep config has an `early_terminate` block.

        Args:
            run_ids: Optimizer run ids to consider for pruning.
            runs: Corresponding run metrics from the latest poll.
        """
        if "early_terminate" not in self._sweep.config:
            return []
        try:
            to_stop = sweeps.stop_runs(
                self._sweep.config,
                self._sweep_runs_for_stop_runs(run_ids, runs),
            )
        except Exception:
            return []
        to_stop_names = {run.name for run in to_stop}
        return [run_id for run_id in run_ids if run_id in to_stop_names]

    @override
    def should_terminate_sweep(self) -> bool:
        """Sweeps library does not implement this, so we return False."""
        return False

    @override
    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Add a terminal run that predates this optimizer to its memory.

        The search treats it as a completed sample. Non-terminal runs are
        ignored.

        Args:
            data: The existing run's state, summary metrics and history.
        """
        if not is_terminal_state(data.state):
            return
        self._record(self._new_run_id(), data)

    @override
    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run that predates this optimizer.

        Only its config is stored, so the search counts it as in flight; the
        next poll fills in metrics via `tell_run`.

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


# ---------------------------------------------------------------------------
# Public entry points.
#
# These free functions are the supported way to run a scheduler; callers
# should not instantiate `WandbOptimizer` directly. Each drives the sweep
# until its scheduler stops: wandb-core owns the scheduling loop and this
# process hosts the optimizer.
# ---------------------------------------------------------------------------


def _parse_sweep_path(sweep: str) -> tuple[str, str, str]:
    """Split an "entity/project/sweep_id" path into its parts."""
    parts = sweep.split("/") if sweep else []
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            f"Expected a sweep path of the form entity/project/sweep_id, got: {sweep!r}"
        )
    entity, project, sweep_id = parts
    return entity, project, sweep_id


def resume_sweep(
    sweep: str,
    *,
    options: SchedulerOptions | None = None,
) -> None:
    """Run a scheduler on a sweep that already exists, until it stops.

    `sweep` is an "entity/project/sweep_id" path string. The sweep's own
    `method` and `parameters` define the search, and its prior runs warm
    start it.

    Args:
        sweep: The sweep to drive, as "entity/project/sweep_id".
        options: How the scheduler drives the sweep; see `SchedulerOptions`.

    Raises:
        ValueError: If `sweep` is not a full sweep path.
    """
    entity, project, sweep_id = _parse_sweep_path(sweep)
    options = options or SchedulerOptions()
    run_scheduler(
        entity=entity,
        project=project,
        sweep_id=sweep_id,
        make_optimizer=WandbOptimizer,
        batch_size=options.batch_size,
        poll_interval=options.poll_interval_s,
    )


def create_sweep(
    entity: str,
    project: str,
    parameters: dict[str, Any],
    metric_name: str,
    *,
    method: str = "bayes",
    goal: str = "minimize",
    program_path: str | None = None,
    options: SchedulerOptions | None = None,
) -> str:
    """Create a sweep from a parameter space, then run its scheduler.

    Args:
        entity: The entity to create the sweep under.
        project: The project to create the sweep under.
        parameters: The sweep config's `parameters` block, mapping each
            name to its space (e.g. `{"lr": {"min": 0.0, "max": 1.0}}`).
        metric_name: The metric runs log and the search optimizes.
        method: The search method: `"bayes"`, `"random"` or `"grid"`.
        goal: Either `"minimize"` or `"maximize"`.
        program_path: The training program recorded in the sweep config.
        options: How the scheduler drives the sweep; see `SchedulerOptions`.

    Returns:
        The sweep's id.

    Raises:
        ValueError: If `entity`, `project`, `parameters` or `metric_name`
            is empty.
    """
    if not entity or not project or not metric_name:
        raise ValueError("entity, project and metric_name must be non-empty")
    if not parameters:
        raise ValueError("parameters must be non-empty")

    config: dict[str, Any] = {
        "method": method,
        "metric": {"name": metric_name, "goal": goal},
        "parameters": parameters,
        "scheduler": {"engine": "wandb"},
    }
    if program_path is not None:
        config["program"] = program_path

    return create_sweep_from_config(config, entity, project, options=options)


def create_sweep_from_config(
    config: dict[str, Any],
    entity: str,
    project: str,
    *,
    options: SchedulerOptions | None = None,
) -> str:
    """Create a sweep from `config`, then run its scheduler.

    Args:
        config: The sweep config; its `scheduler.engine` must be `"wandb"`
            if it sets one.
        entity: The entity to create the sweep under.
        project: The project to create the sweep under.
        options: How the scheduler drives the sweep; see `SchedulerOptions`.

    Returns:
        The sweep's id.

    Raises:
        ValueError: If `config` selects another engine, or if `entity` or
            `project` is empty.
    """
    if not entity or not project:
        raise ValueError("entity and project must be non-empty")

    engine = (config.get("scheduler") or {}).get("engine", "wandb")
    if engine != "wandb":
        raise ValueError(
            f"config selects the {engine!r} engine; use that engine's "
            f"create_sweep_from_config instead."
        )

    options = options or SchedulerOptions()
    # The server leaves the search to this scheduler only when the config
    # records an engine, so make sure it does.
    config = {**config, "scheduler": {"engine": "wandb"}}
    sweep_id = wandb_sweep(config, entity=entity, project=project)
    run_scheduler(
        entity=entity,
        project=project,
        sweep_id=sweep_id,
        make_optimizer=WandbOptimizer,
        batch_size=options.batch_size,
        poll_interval=options.poll_interval_s,
    )
    return sweep_id
