from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from wandb.apis.public import Sweep
from wandb.sdk.sweeps.run_state import RunState


@dataclass
class ConfigValue:
    """One hyperparameter in the server's wrapped form: `{"value": <v>}`."""

    value: Any


@dataclass
class RunConfig:
    """A run's hyperparameters, keyed by parameter name.

    Each value is wrapped so that both the flat form callers think in
    (`flat_dict`) and the form the server and sweep agent exchange
    (`wire_dict`) are named rather than passed around as bare dicts.
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
        # A define-by-run `trial_constructor` naturally returns the flat
        # `{param: value}` mapping from `trial.params`; accept that and
        # normalize it to a `RunConfig` here so every suggestion the executor
        # sees can be serialized the same way (`config.model_dump()`),
        # regardless of which optimizer (or user constructor) built it.
        if not isinstance(self.config, RunConfig):
            self.config = RunConfig.from_values(self.config)


@dataclass
class Run:
    """A sweep run as the optimizer sees it, without its metrics.

    `wandb_run_id` is the id W&B assigned the run, which a scheduler maps back
    to the `RunSuggestion.run_id` the optimizer handed out.
    """

    config: RunConfig
    state: RunState
    wandb_run_id: str


@dataclass
class RunWithMetrics(Run):
    """A `Run` together with the metrics it has reported so far.

    `summary_metrics` is the run's latest summary; `history_metrics` is the
    sampled per-step history, which early terminators read.
    """

    summary_metrics: dict[str, Any]
    history_metrics: list[dict[str, Any]]


def is_terminal_state(state: RunState) -> bool:
    """Return True if the run has stopped (is terminal), else False.

    In-flight states (running/pending/preempting/preempted/unknown) return
    False. Used to decide whether a run's result can be reported to the
    optimizer.
    """
    return state in (
        RunState.FINISHED,
        RunState.FAILED,
        RunState.CRASHED,
        RunState.KILLED,
        RunState.PREEMPTED,
    )


class Optimizer(ABC):
    """An external optimizer that supports an ask-tell interface.

    A scheduler asks the optimizer for runs to start, then tells the run
    results back to the optimizer as they progress.

    Subclasses may read the protected `_sweep` attribute, the `Sweep`
    being optimized.
    """

    def __init__(self, sweep: Sweep):
        self._sweep = sweep

    @abstractmethod
    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion] | None:
        """Propose up to `n` runs to start next.

        Fewer than `n` may come back when the search space is nearly
        exhausted. Returning an empty sequence means the search space is
        exhausted: a scheduler takes it as the end of the sweep and finishes
        it. Returning None declines to propose for now (e.g. the strategy
        needs results from in-flight runs first); the scheduler asks again
        on a later poll.

        Args:
            n: The maximum number of runs to propose.
        """
        ...

    @abstractmethod
    def tell_run(self, run_id: Any, data: RunWithMetrics) -> None:
        """Report the latest state and metrics of a run this optimizer proposed.

        Called on each poll while the run is in flight, and once more when it
        reaches a terminal state.

        Args:
            run_id: The `RunSuggestion.run_id` this optimizer handed out.
            data: The run's current state, summary metrics and history.
        """
        ...

    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Report a *terminal* run that already existed in the sweep at startup.

        Unlike `tell_run`, there is no optimizer-side run id because the run was
        not produced by this optimizer's `ask_n_runs`. Override to warm-start
        from prior results; the default is a no-op.
        """
        return None

    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an *in-flight* (RUNNING/PENDING) run that existed at startup.

        Args:
            data: The existing run's config and state, without metrics.

        Returns:
            The optimizer-side run id to track the run by, in which case
            later polls report its metrics via `tell_run`, or None to
            leave the run untracked. The default adopts nothing.
        """
        return None

    def metric_value(self, metrics: dict[str, Any]) -> Any:
        """Return the objective value for the sweep's configured metric."""
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

    @property
    def sweep_name(self) -> str:
        """The name of the sweep this optimizer searches."""
        return self._sweep.name

    def prune_run(self, run_id: Any, data: RunWithMetrics) -> bool:
        """Return True if the run should be pruned.

        Override to stop single runs early, the default prunes nothing.
        The default `prune_runs` calls this for each polled run.

        Args:
            run_id: The `RunSuggestion.run_id` the optimizer handed out.
            data: The run's current state, summary and history metrics.
        """
        return False

    def prune_runs(
        self, run_ids: Sequence[str], runs: Sequence[RunWithMetrics]
    ) -> Sequence[str]:
        """Return the optimizer run ids that should be pruned.

        Override to decide early stopping across runs as a batch; the
        default delegates calls to `prune_run` for each run.

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
