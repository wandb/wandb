from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import wandb
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.sweep_info import SweepInfo


@dataclass
class ConfigValue:
    """One hyperparameter in the server's wrapped form: `{"value": <v>}`."""

    value: Any


@dataclass
class RunConfig:
    """A run's hyperparameters, keyed by parameter name.

    Values are wrapped so the flat form (`flat_dict`) and the server/agent
    wire form (`wire_dict`) are named rather than bare dicts.
    """

    config: dict[str, ConfigValue]

    @classmethod
    def from_values(cls, values: dict[str, Any]) -> RunConfig:
        """Build a `RunConfig` from a flat `{param: value}` mapping."""
        return cls({name: ConfigValue(value=value) for name, value in values.items()})

    def flat_dict(self) -> dict[str, Any]:
        """The flat `{param: value}` mapping."""
        return {name: cv.value for name, cv in self.config.items()}

    def wire_dict(self) -> dict[str, dict[str, Any]]:
        """The server/agent wire form `{param: {"value": v}}`."""
        return {name: {"value": cv.value} for name, cv in self.config.items()}

    def __getitem__(self, key: str) -> ConfigValue:
        return self.config[key]


@dataclass
class RunSuggestion:
    """A run the optimizer proposes, with the id it will track it by.

    `run_id` is the optimizer's own id, not a W&B run id: the run does not
    exist yet when it is proposed.
    """

    config: RunConfig
    run_id: str

    def __post_init__(self) -> None:
        # Accept the flat mapping third-party optimizers produce, so every
        # suggestion the executor sees serializes the same way.
        if not isinstance(self.config, RunConfig):
            self.config = RunConfig.from_values(self.config)


@dataclass
class Run:
    """A sweep run as the optimizer sees it, without its metrics.

    The scheduler maps `wandb_run_id` back to the `RunSuggestion.run_id` the
    optimizer handed out.
    """

    config: RunConfig
    state: RunState
    wandb_run_id: str


@dataclass
class RunWithMetrics(Run):
    """A `Run` plus its latest summary and sampled per-step history."""

    summary_metrics: dict[str, Any]
    history_metrics: list[dict[str, Any]]


def is_terminal_state(state: RunState) -> bool:
    """Return True if the run has stopped, so its result can be reported."""
    return state in (
        RunState.FINISHED,
        RunState.FAILED,
        RunState.CRASHED,
        RunState.KILLED,
        RunState.PREEMPTED,
    )


@dataclass(frozen=True)
class Objective:
    """One metric an optimizer searches over.

    Attributes:
        metric_name: The run summary metric to optimize.
        goal: Either "minimize" or "maximize".
    """

    metric_name: str
    goal: str


def sweep_objectives(config: dict[str, Any]) -> list[Objective]:
    """Return the objectives a sweep config declares in metrics or metric.

    Args:
        config: A sweep config, such as `SweepInfo.config`.

    Raises:
        ValueError: If the config sets both, or a metric has no name.
    """
    metrics = config.get("metrics")
    metric = config.get("metric")
    if metrics and metric:
        raise ValueError("The sweep config sets both metric and metrics.")
    declared = metrics or ([metric] if metric else [])
    objectives = []
    for i, entry in enumerate(declared):
        if not entry.get("name"):
            raise ValueError(f"The sweep config's metric {i} has no name.")
        objectives.append(Objective(entry["name"], entry.get("goal", "minimize")))
    return objectives


def check_objectives(config: dict[str, Any], objectives: Sequence[Objective]) -> None:
    """Check an optimizer's objectives against the sweep config's.

    A config that declares no objectives accepts any non-empty list.

    Args:
        config: The sweep's config.
        objectives: The objectives the optimizer searches over.

    Raises:
        ValueError: If there are no objectives or they differ from the config's.
    """
    if not objectives:
        raise ValueError(
            "The optimizer has no objectives. Declare metric or metrics in the"
            " sweep config, or set them in the scheduler.optimizer function."
        )
    declared = sweep_objectives(config)
    if not declared:
        return
    if len(objectives) != len(declared):
        raise ValueError(
            f"The optimizer has {len(objectives)} objectives but the sweep"
            f" config declares {len(declared)}."
        )
    for got, want in zip(objectives, declared, strict=True):
        if got.metric_name != want.metric_name:
            raise ValueError(
                f"The optimizer's objective {got.metric_name!r} does not match"
                f" the sweep config's metric {want.metric_name!r}."
            )
        if got.goal != want.goal:
            raise ValueError(
                f"The optimizer's goal for {got.metric_name!r} is {got.goal!r}"
                f" but the sweep config's is {want.goal!r}."
            )


class Optimizer(ABC):
    """An external optimizer that supports an ask-tell interface.

    A scheduler asks for runs to start, then tells results back as the runs
    progress. Subclasses may read the protected `_sweep` attribute.

    Run ids handed out by `ask_n_runs` and `tell_existing_active_run` must be
    unique across both for the optimizer's lifetime: the scheduler routes
    tells and prunes by id alone.
    """

    def __init__(self, sweep: SweepInfo, objectives: Sequence[Objective]):
        self._sweep = sweep
        self._objectives = tuple(objectives)

    def route_library_logs(self, handler: logging.Handler) -> Callable[[], None]:
        """Send the search library's log records to `handler`.

        Replaces the library's own console output for the scheduler session,
        so each record reaches the terminal exactly once.

        Args:
            handler: Receives the library's log records.

        Returns:
            A function that restores the library's own console output.
        """
        return lambda: None

    @abstractmethod
    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion] | None:
        """Propose up to `n` runs to start next.

        An empty sequence means the search space is exhausted and the
        scheduler finishes the sweep. None only declines for now (e.g. the
        strategy needs in-flight results first) and is retried on a later
        poll.

        Args:
            n: The maximum number of runs to propose.
        """
        ...

    @abstractmethod
    def tell_run(self, run_id: Any, data: RunWithMetrics) -> None:
        """Report the latest state and metrics of a run this optimizer proposed.

        Called on each poll while the run is in flight, and once more when it
        reaches a terminal state. A run returned from `prune_runs` keeps
        getting these calls until the scheduler manages to stop it, so
        implementations that finalize a run at prune time must treat them as
        no-ops rather than raise.

        Args:
            run_id: The `RunSuggestion.run_id` this optimizer handed out.
            data: The run's current state, summary metrics and history.
        """
        ...

    def forget_run(self, run_id: Any) -> None:
        """Release a proposed run that will never start.

        Called when the scheduler could not durably schedule a suggestion; no
        `tell_run` follows for the id. The default reports a failed run with
        no metrics; override to drop the point entirely so it can be proposed
        again.

        Args:
            run_id: The `RunSuggestion.run_id` this optimizer handed out.
        """
        self.tell_run(
            run_id,
            RunWithMetrics(
                config=RunConfig({}),
                state=RunState.FAILED,
                wandb_run_id="",
                summary_metrics={},
                history_metrics=[],
            ),
        )

    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Report a *terminal* run that already existed in the sweep at startup.

        There is no optimizer-side run id: the run did not come from
        `ask_n_runs`. Override to warm-start from prior results; the default
        is a no-op.

        Args:
            data: The finished run's final state, summary metrics and history.
        """
        return None

    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an *in-flight* (RUNNING/PENDING) run that existed at startup.

        Args:
            data: The existing run's config and state, without metrics.

        Returns:
            The optimizer-side run id to track the run by, whose metrics
            later polls report via `tell_run`, or None to leave the run
            untracked. The default adopts nothing.
        """
        return None

    def metric_value(self, metrics: dict[str, Any]) -> Any:
        """Return the value of the first objective metric.

        Args:
            metrics: One run's metrics, keyed by metric name.
        """
        return metrics.get(self._objectives[0].metric_name)

    @property
    def objectives(self) -> tuple[Objective, ...]:
        """The objectives this optimizer searches over, in order."""
        return self._objectives

    def metric_names(self) -> list[str]:
        """Return the objective metric names, in the optimizer's order."""
        return [objective.metric_name for objective in self._objectives]

    def metric_goals(self) -> list[str]:
        """Return the objective goals, in `metric_names` order."""
        return [objective.goal for objective in self._objectives]

    def objective_values(self, metrics: dict[str, Any]) -> list[Any] | None:
        """Return a run's objective values, or None if any of them is missing.

        Args:
            metrics: One run's metrics, keyed by metric name.
        """
        values = [metrics.get(name) for name in self.metric_names()]
        if any(value is None for value in values):
            return None
        return values

    @property
    def sweep_name(self) -> str:
        """The name of the sweep this optimizer searches."""
        return self._sweep.name

    @property
    def engine(self) -> str:
        """The search engine named in the sweep's scheduler config.

        Returns:
            The `scheduler.engine` value, or `wandb` when the sweep
            does not name one.
        """
        scheduler = self._sweep.config.get("scheduler") or {}
        return str(scheduler.get("engine") or "wandb")

    def prune_run(self, run_id: Any, data: RunWithMetrics) -> bool:
        """Return True if the run should be pruned.

        Called by the default `prune_runs` for each polled run. Override to
        stop single runs early; the default prunes nothing. Returning True is
        final, as described in `prune_runs`.

        Args:
            run_id: The `RunSuggestion.run_id` the optimizer handed out.
            data: The run's current state, summary and history metrics.
        """
        return False

    def prune_runs(
        self, run_ids: Sequence[str], runs: Sequence[RunWithMetrics]
    ) -> Sequence[str]:
        """Return the optimizer run ids that should be pruned.

        Override to decide early stopping as a batch; the default delegates to
        `prune_run`. Returning an id is final: the scheduler keeps trying to
        stop the run until the backend accepts, and never offers the id
        again, so implementations should finalize the run's trial here.

        Args:
            run_ids: Optimizer run ids to consider for pruning.
            runs: The corresponding runs' latest state and metrics.
        """
        return [
            run_id
            for run_id, run in zip(run_ids, runs, strict=True)
            if self.prune_run(run_id, run)
        ]

    def should_terminate_sweep(self) -> bool:
        """Return True if the sweep should be terminated."""
        return False


def make_optimizer(sweep: SweepInfo) -> Optimizer:
    """Build the optimizer for the engine a scheduler-enabled sweep names.

    The local scheduler only drives sweeps that opted out of server-side
    search, which the `scheduler.engine` block records.

    Raises:
        wandb.Error: If the engine is missing or unsupported, its
            configuration can't be loaded, or its objectives differ from
            the sweep config's.
    """
    optimizer = _build_engine_optimizer(sweep)
    try:
        check_objectives(sweep.config, optimizer.objectives)
    except ValueError as e:
        raise wandb.Error(str(e)) from e
    return optimizer


def _build_engine_optimizer(sweep: SweepInfo) -> Optimizer:
    """Build the optimizer for the sweep's `scheduler.engine`."""
    # Each engine module is imported lazily so a missing engine dependency
    # only fails sweeps that use it.
    scheduler_config: dict[str, Any] = sweep.config.get("scheduler") or {}
    engine: str | None = scheduler_config.get("engine")
    if engine == "wandb":
        from wandb.sdk.sweeps.scheduler.wandb import build_wandb_optimizer

        return build_wandb_optimizer(sweep)
    if engine == "optuna":
        from wandb.sdk.sweeps.scheduler.optuna import build_optuna_optimizer

        return build_optuna_optimizer(sweep)
    if engine == "ax":
        from wandb.sdk.sweeps.scheduler.ax import build_ax_optimizer

        return build_ax_optimizer(sweep)
    raise wandb.Error(f"Unsupported engine: {engine}")
