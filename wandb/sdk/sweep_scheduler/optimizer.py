from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from wandb.apis.public import Sweep
from wandb.sdk.launch.sweeps.scheduler import RunState


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
class RunEnriched(Run):
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

    Pure search strategy: it proposes runs and ingests their results, holding no
    scheduling I/O. A `Scheduler` drives it.
    """

    def __init__(self, sweep: Sweep):
        self._sweep = sweep

    @abstractmethod
    def next_n_runs(self, n: int) -> Sequence[RunSuggestion]:
        """Propose up to `n` runs to start next.

        Fewer than `n` may come back when the search space is nearly exhausted
        or the strategy needs results before proposing more. Returning nothing
        at all means the search space is exhausted: a scheduler takes it as the
        end of the sweep and finishes it, so a strategy that is only waiting on
        results must propose at least one run.

        Args:
            n: The maximum number of runs to propose.
        """
        ...

    @abstractmethod
    def tell_run(self, run_id: Any, data: RunEnriched) -> None:
        """Report the latest state and metrics of a run this optimizer proposed.

        Called on each poll while the run is in flight, and once more when it
        reaches a terminal state.

        Args:
            run_id: The `RunSuggestion.run_id` this optimizer handed out.
            data: The run's current state, summary metrics and history.
        """
        ...

    def tell_existing_finished_run(self, data: RunEnriched) -> None:
        """Report a *terminal* run that already existed in the sweep at startup.

        Unlike `tell_run`, there is no optimizer-side run id because the run was
        not produced by this optimizer's `next_n_runs`. Override to warm-start
        from prior results; the default is a no-op.
        """
        return None

    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an *in-flight* (RUNNING/PENDING) run that existed at startup.

        `data` has no metrics; the next poll reports them via `tell_run`.
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
        return self._sweep.name

    def prune_run(self, run_id: Any, data: RunEnriched) -> bool:
        """Return True if the run should be pruned."""
        return False

    def should_terminate_sweep(self) -> bool:
        """Return True if the sweep should be terminated."""
        return False
