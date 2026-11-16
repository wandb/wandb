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


NESTED_NAME_DELIMITER = "."
"""Joins the path to a nested sweep parameter into its flat name."""


def flatten_sweep_parameters(
    parameters: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Flatten a sweep's `parameters` block into leaf specs by flat name.

    W&B nests a parameter whose spec holds its own `parameters` block:
    `optimizer: {parameters: {lr: ...}}` sets `config["optimizer"]["lr"]`.
    Optuna and Ax search a flat space, so a nested leaf is named by its path
    joined with `NESTED_NAME_DELIMITER`, here `optimizer.lr`.

    Raises:
        ValueError: If two parameters flatten to the same name.
    """
    return {name: spec for name, (_, spec) in _leaves_by_flat_name(parameters).items()}


def _leaves_by_flat_name(
    parameters: dict[str, Any],
    prefix: tuple[str, ...] = (),
    leaves: dict[str, tuple[tuple[str, ...], dict[str, Any]]] | None = None,
) -> dict[str, tuple[tuple[str, ...], dict[str, Any]]]:
    """Map each leaf parameter's flat name to its path and spec.

    Leaves keep the order the sweep config declares them in.

    Raises:
        ValueError: If two parameters flatten to the same name.
    """
    if leaves is None:
        leaves = {}
    for key, spec in parameters.items():
        path = (*prefix, key)
        if "parameters" in spec:
            _leaves_by_flat_name(spec["parameters"], path, leaves)
            continue
        name = NESTED_NAME_DELIMITER.join(path)
        if name in leaves:
            raise ValueError(
                f"Sweep parameters {leaves[name][0]!r} and {path!r} both"
                f" flatten to the name {name!r}; rename one of them."
            )
        leaves[name] = (path, spec)
    return leaves


@dataclass(frozen=True)
class NestedParameters:
    """Where each nested sweep parameter sits in a run's config.

    Converts between the flat names Optuna and Ax search over (see
    `flatten_sweep_parameters`) and the nested config a run receives.
    """

    paths: dict[str, tuple[str, ...]]
    """The path of each nested leaf by flat name, without top-level ones."""

    @classmethod
    def from_sweep_parameters(cls, parameters: dict[str, Any]) -> NestedParameters:
        """Find the nested leaves of a sweep's `parameters` block.

        Raises:
            ValueError: If two parameters flatten to the same name.
        """
        leaves = _leaves_by_flat_name(parameters)
        return cls({name: path for name, (path, _) in leaves.items() if len(path) > 1})

    def nest(self, values: dict[str, Any]) -> dict[str, Any]:
        """Nest flat parameter values into the shape of a run's config.

        Names that aren't nested sweep parameters stay at the top level.
        """
        config: dict[str, Any] = {}
        for name, value in values.items():
            *parents, leaf = self.paths.get(name, (name,))
            node = config
            for parent in parents:
                node = node.setdefault(parent, {})
            node[leaf] = value
        return config

    def flatten(self, config: dict[str, Any]) -> dict[str, Any]:
        """Name a run config's nested sweep parameter values by flat name.

        The inverse of `nest`. A nested value missing from the config is left
        out, and other top-level keys are kept as they are.
        """
        roots = {path[0] for path in self.paths.values()}
        values = {key: value for key, value in config.items() if key not in roots}
        for name, path in self.paths.items():
            node: Any = config
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    break
                node = node[key]
            else:
                values[name] = node
        return values


class Optimizer(ABC):
    """An external optimizer that supports an ask-tell interface.

    A scheduler asks for runs to start, then tells results back as the runs
    progress. Subclasses may read the protected `_sweep` attribute.

    Run ids handed out by `ask_n_runs` and `tell_existing_active_run` must be
    unique across both for the optimizer's lifetime: the scheduler routes
    tells and prunes by id alone.
    """

    def __init__(self, sweep: SweepInfo):
        self._sweep = sweep
        self.validate_sweep_objective()

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
    def validate_sweep_objective(self) -> None:
        """Raise if the optimizer's objective disagrees with the sweep's.

        Called from `__init__` so a mismatch surfaces before the sweep runs.
        """
        ...

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
        """Return the objective value for the sweep's configured metric.

        Args:
            metrics: One run's metrics, keyed by metric name.
        """
        return metrics.get(self.metric_key())

    def metric_key(self) -> str:
        """Return the name of the sweep's objective metric.

        Raises:
            ValueError: If the sweep config declares no metric name.
        """
        metric = self._sweep.config.get("metric")
        if not metric or "name" not in metric:
            raise ValueError(
                "Sweep config has no metric; cannot determine the objective value."
            )
        return metric["name"]

    def metric_names(self) -> list[str]:
        """Return the sweep's objective metric names, in declaration order.

        A multi-objective sweep names them in `metrics`; a single-objective one
        in `metric`.
        """
        metrics = self._sweep.config.get("metrics")
        if metrics is not None:
            return [metric["name"] for metric in metrics if "name" in metric]
        return [self.metric_key()]

    def metric_goals(self) -> list[str]:
        """Return the sweep's objective goals, ordered as `metric_names`."""
        metrics = self._sweep.config.get("metrics")
        if metrics is None:
            metrics = [self._sweep.config.get("metric") or {}]
        return [str(metric.get("goal", "minimize")).lower() for metric in metrics]

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

    @abstractmethod
    def has_terminator(self) -> bool:
        """Whether this optimizer was given a sweep-level terminator."""
        ...

    def should_terminate_sweep(self) -> bool:
        """Return True if the sweep should be terminated."""
        return False


def make_optimizer(sweep: SweepInfo) -> Optimizer:
    """Build the optimizer for the engine a scheduler-enabled sweep names.

    The local scheduler only drives sweeps that opted out of server-side
    search, which the `scheduler.engine` block records.

    Raises:
        wandb.Error: If the engine is missing or unsupported, or its
            configuration can't be loaded.
    """
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
