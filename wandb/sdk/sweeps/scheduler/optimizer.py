from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

import wandb
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.sweep_info import SweepInfo

_T = TypeVar("_T")


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

    def should_terminate_sweep(self) -> bool:
        """Return True if the sweep should be terminated."""
        return False


def convert_parameters(
    parameters: object,
    convert: Callable[[str, dict[str, Any]], _T],
) -> dict[str, _T]:
    """Convert each spec in a sweep config's `parameters` block.

    Args:
        parameters: The sweep config's `parameters` value.
        convert: Converts one parameter's name and spec for an engine.

    Returns:
        The converted specs, keyed by parameter name.

    Raises:
        ValueError: If the block or a spec is malformed, naming the
            parameter at fault.
    """
    if not isinstance(parameters, dict):
        raise ValueError(  # noqa: TRY004
            "The sweep config's parameters must map each parameter name to"
            f" its spec, not {parameters!r}."
        )
    converted: dict[str, _T] = {}
    for name, spec in parameters.items():
        if not isinstance(spec, dict):
            raise ValueError(  # noqa: TRY004
                f"parameters.{name} must be a mapping such as"
                f" `{{min: 0, max: 1}}`, not {spec!r}."
            )
        try:
            converted[name] = convert(name, spec)
        except KeyError as e:
            raise ValueError(
                f"parameters.{name} is missing {e.args[0]!r}, which its"
                " distribution requires."
            ) from None
        except TypeError as e:
            raise ValueError(
                f"parameters.{name} has a value of the wrong type; min, max and"
                f" q must be numbers and values must be a list ({e})."
            ) from e
        except ValueError as e:
            raise ValueError(f"parameters.{name} is invalid: {e}") from e
    return converted


def check_sweep_metrics(config: dict[str, Any]) -> None:
    """Check the shape of a sweep config's `metric` or `metrics` blocks.

    Args:
        config: The sweep config.

    Raises:
        ValueError: If `metrics` is not a non-empty list of named mappings,
            or `metric` is set but not a mapping.
    """
    example = "`{name: loss, goal: minimize}`"
    metrics = config.get("metrics")
    if metrics is None:
        metric = config.get("metric")
        if metric and not isinstance(metric, dict):
            raise ValueError(
                f"The sweep config's metric must be a mapping such as {example},"
                f" not {metric!r}."
            )
        return
    if not isinstance(metrics, list):
        raise ValueError(  # noqa: TRY004
            "The sweep config's metrics must be a list of mappings such as"
            f" {example}, not {metrics!r}."
        )
    if not metrics:
        raise ValueError(
            "The sweep config's metrics must list at least one metric such as"
            f" {example}; remove metrics or add one."
        )
    for i, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            raise ValueError(  # noqa: TRY004
                f"metrics[{i}] in the sweep config must be a mapping such as"
                f" {example}, not {metric!r}."
            )
        if "name" not in metric:
            raise ValueError(
                f"metrics[{i}] in the sweep config has no name; set"
                f" metrics[{i}].name to the metric to optimize."
            )


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
    scheduler_config: object = sweep.config.get("scheduler") or {}
    if not isinstance(scheduler_config, dict):
        raise wandb.Error(
            "The sweep config's scheduler must be a mapping with an engine key,"
            f" such as `scheduler: {{engine: optuna}}`, not {scheduler_config!r}."
        )
    engine: str | None = scheduler_config.get("engine")
    if engine == "wandb":
        from wandb.sdk.sweeps.scheduler.wandb import build_wandb_optimizer

        return build_wandb_optimizer(sweep, scheduler_config)
    if engine == "optuna":
        from wandb.sdk.sweeps.scheduler.optuna import build_optuna_optimizer

        return build_optuna_optimizer(sweep, scheduler_config)
    if engine == "ax":
        from wandb.sdk.sweeps.scheduler.ax import build_ax_optimizer

        return build_ax_optimizer(sweep, scheduler_config)
    raise wandb.Error(
        "The sweep config's scheduler.engine must be one of wandb, optuna or"
        f" ax, not {engine!r}."
    )
