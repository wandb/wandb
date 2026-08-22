from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wandb.errors import term
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.sweep_info import SweepInfo

if TYPE_CHECKING:
    import wandb


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
        self._controller_run: wandb.Run | None = None
        self.validate_sweep_objective()

    def attach_controller_run(self, run: wandb.Run | None) -> None:
        """Send this optimizer's `log()` lines to the sweep's controller run.

        Called by the scheduler session. Lines are attributed to this
        optimizer's engine instead of captured as scheduler output.

        Args:
            run: The attached controller run, or None when the sweep
                has none or the attach failed.
        """
        self._controller_run = run

    def log(self, message: str) -> None:
        """Log a line to the terminal, attributed to this optimizer's engine.

        Inside a `run_scheduler` session that attached the sweep's
        controller run, the line is written to that run under this
        optimizer's engine name rather than captured as scheduler
        output.

        Args:
            message: The line to log.
        """
        if self._controller_run is None:
            term.termlog(message)
            return

        from wandb.sdk.lib import console_capture

        with console_capture.uncaptured():
            term.termlog(message)
        try:
            self._controller_run.write_logs(message, label=self.engine)
        except Exception:
            # A failed write costs this line on the run, never the sweep.
            pass

    def captured_loggers(self) -> Sequence[str]:
        """Names of Python loggers the scheduler surfaces to the user.

        During a `run_scheduler` session, records these loggers emit are
        printed to the terminal in place of the libraries' own stream
        output, and stream to the sweep's controller run when one is
        attached. Override to expose an optimizer library's internal
        logging; the default captures nothing.
        """
        return ()

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
        reaches a terminal state. The terminal call also happens for runs
        returned from `prune_runs`, so implementations that finalize a run at
        prune time must treat it as a no-op rather than raise.

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
        stop single runs early; the default prunes nothing.

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
        `prune_run`. An already-returned id may be offered again while its run
        has not stopped, and implementations must tolerate that.

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
