from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, List

from pydantic import BaseModel, RootModel

from wandb.apis.public import Sweep
from wandb.sdk.launch.sweeps.scheduler import RunState


class ConfigValue(BaseModel):
    """One hyperparameter in the server's wrapped form: ``{"value": <v>}``."""

    value: Any


class RunConfig(RootModel[dict[str, ConfigValue]]):
    """A run's hyperparameters in the W&B sweep wire format: ``{param: {"value": v}}``.

    This is exactly the structure the sweep agent reads each parameter from and the
    server forwards to it verbatim, so a `RunSuggestion` carries it unmodified and
    the executor enqueues ``model_dump()`` directly. Build one from a flat
    ``{param: value}`` mapping with `from_values`, and read that flat mapping back
    via `values`.
    """

    @classmethod
    def from_values(cls, values: dict[str, Any]) -> RunConfig:
        """Build a `RunConfig` from a flat ``{param: value}`` mapping."""
        return cls({name: ConfigValue(value=value) for name, value in values.items()})

    @property
    def values(self) -> dict[str, Any]:
        """The flat ``{param: value}`` mapping."""
        return {name: cv.value for name, cv in self.root.items()}


@dataclass
class RunSuggestion:
    config: RunConfig
    run_id: str

    def __post_init__(self) -> None:
        # A define-by-run `trial_constructor` naturally returns the flat
        # ``{param: value}`` mapping from ``trial.params``; accept that and
        # normalize it to a `RunConfig` here so every suggestion the executor
        # sees can be serialized the same way (``config.model_dump()``),
        # regardless of which optimizer (or user constructor) built it.
        if not isinstance(self.config, RunConfig):
            self.config = RunConfig.from_values(self.config)


@dataclass
class Run:
    config: dict
    state: RunState
    wandb_run_id: str


@dataclass
class RunEnriched(Run):
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


class Optimizer(ABC):
    """An external optimizer that supports an ask-tell interface.

    Pure search strategy: it proposes runs and ingests their results, holding no
    scheduling I/O. A `Scheduler` drives it.
    """

    def __init__(self, sweep: Sweep):
        self._sweep = sweep

    @abstractmethod
    def next_n_runs(self, n: int) -> Iterable[RunSuggestion]: ...

    @abstractmethod
    def tell_run(self, run_id: Any, data: RunEnriched) -> None: ...

    def tell_existing_finished_run(self, data: RunEnriched) -> None:
        """Report a *terminal* run that already existed in the sweep at startup.

        Unlike `tell_run`, there is no optimizer-side run id because the run was
        not produced by this optimizer's `next_n_runs`. Override to warm-start
        from prior results; the default is a no-op.
        """
        return None

    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an *in-flight* (RUNNING/PENDING) run that already existed in the
        sweep at startup. data has no metrics, as the next poll reports them via `tell_run`."""
        return None

    def metric_value(self, metrics: dict[str, Any]) -> Any:
        """Return the objective value for the sweep's configured metric."""
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

    def prune_run(self, run_id: Any, data: RunEnriched) -> bool:
        """Return True if the run should be pruned."""
        return False
