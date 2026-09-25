from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from wandb.sdk.sweeps.scheduler.optimizer import Run, RunWithMetrics, is_terminal_state
from wandb.sdk.sweeps.sweep_info import SweepInfo

TrialT = TypeVar("TrialT")

# Trial labels linking a library's trials to the sweep, so optimizer state the
# caller persisted and reloaded is resumed on warm start, not refilled.
SWEEP_LABEL = "wandb_sweep"
WANDB_RUN_ID_LABEL = "wandb_run_id"

# A claimed trial that already finished, so its run has nothing left to tell.
_FINISHED = object()


class ResumableTrials(ABC, Generic[TrialT]):
    """One optimizer library's trials, as a `TrialResumer` needs them.

    Run ids are the ids the optimizer tracks its runs by. A `TrialResumer`
    keeps only run ids, never trials, so methods given a run id look the
    trial up themselves.
    """

    @abstractmethod
    def existing(self) -> Iterable[TrialT]:
        """Return every trial the library holds, uncopied."""
        ...

    @abstractmethod
    def run_id(self, trial: TrialT) -> Any:
        """Return the run id the optimizer tracks a trial by."""
        ...

    @abstractmethod
    def labels(self, trial: TrialT) -> Mapping[str, Any]:
        """Return the labels stored on a trial."""
        ...

    @abstractmethod
    def is_running(self, trial: TrialT) -> bool:
        """Return whether a trial is still waiting for its result."""
        ...

    @abstractmethod
    def label(self, run_id: Any, labels: dict[str, Any]) -> None:
        """Store labels on the tracked trial with this run id."""
        ...

    @abstractmethod
    def matches(self, run_id: Any, config: dict[str, Any]) -> bool:
        """Return whether the trial with this run id has a run's config."""
        ...

    @abstractmethod
    def resume(self, run_id: Any) -> Any:
        """Track the existing running trial with this run id again.

        Returns:
            The run id to track the trial's run by.
        """
        ...

    @abstractmethod
    def add_finished(self, data: RunWithMetrics) -> None:
        """Record a terminal run the library has no trial for."""
        ...

    @abstractmethod
    def adopt_new(self, data: Run) -> Any:
        """Track an in-flight run the library has no trial for.

        Returns:
            The run id to track the run by, or None to leave it untracked.
        """
        ...


@dataclass
class _Index:
    """Run ids of the trials a reloaded library holds for the sweep."""

    # W&B run id to the run id of its still-running trial.
    running_by_run: dict[str, Any] = field(default_factory=dict)
    # W&B run ids whose trial already finished.
    finished_runs: set[str] = field(default_factory=set)
    # Run ids of the sweep's running trials no run was seen for yet.
    unlinked_running: list[Any] = field(default_factory=list)


class TrialResumer(Generic[TrialT]):
    """Warm-starts an optimizer whose library may hold the sweep's trials.

    A caller can hand over optimizer state reloaded from their own storage.
    Each trial is labeled with its sweep when created and with its W&B run
    id once a run is seen, so warm start resumes a run's own trial rather
    than adding the run again.

    Only W&B run ids and run ids are kept, never trials. The library's
    trials are listed on the first warm-start call, not before, and the
    index is dropped for good by `end_warm_start`.

    Args:
        sweep: The sweep the optimizer searches.
        trials: The optimizer library's trials.
        tell_run: The optimizer's `tell_run`, which finalizes a resumed
            trial for a run that already stopped.
    """

    def __init__(
        self,
        sweep: SweepInfo,
        trials: ResumableTrials[TrialT],
        tell_run: Callable[[Any, RunWithMetrics], None],
    ):
        self._trials = trials
        self._tell_run = tell_run
        self._sweep_path = f"{sweep.entity}/{sweep.project}/{sweep.id}"
        # Run ids whose trial carries its W&B run id label while tracked.
        self._linked: set[Any] = set()
        self._index: _Index | None = None
        self._warm_start_over = False

    def _build_index(self) -> _Index:
        """Index the trials the library already holds for this sweep.

        Linked trials are keyed by W&B run id. Trials this sweep asked for
        but never saw polled carry no run id; running ones are kept so warm
        start can still match them to their run by params.
        """
        index = _Index()
        for trial in self._trials.existing():
            labels = self._trials.labels(trial)
            wandb_run_id = labels.get(WANDB_RUN_ID_LABEL)
            running = self._trials.is_running(trial)
            if wandb_run_id is not None:
                if running:
                    index.running_by_run[wandb_run_id] = self._trials.run_id(trial)
                else:
                    index.finished_runs.add(wandb_run_id)
            elif running and labels.get(SWEEP_LABEL) == self._sweep_path:
                index.unlinked_running.append(self._trials.run_id(trial))
        return index

    def end_warm_start(self) -> None:
        """Drop the index for good; later runs are the optimizer's own."""
        self._warm_start_over = True
        self._index = None

    def run_labels(self, wandb_run_id: str) -> dict[str, Any]:
        """The labels marking a trial as a given run of this sweep."""
        return {SWEEP_LABEL: self._sweep_path, WANDB_RUN_ID_LABEL: wandb_run_id}

    def label_new(self, run_id: Any) -> None:
        """Label a trial the optimizer just created as this sweep's."""
        self._trials.label(run_id, {SWEEP_LABEL: self._sweep_path})

    def link(self, run_id: Any, wandb_run_id: str) -> None:
        """Label a tracked trial with its W&B run id, once."""
        if run_id in self._linked or not wandb_run_id:
            return
        self._trials.label(run_id, {WANDB_RUN_ID_LABEL: wandb_run_id})
        self._linked.add(run_id)

    def unlink(self, run_id: Any) -> None:
        """Forget a trial that is no longer tracked."""
        self._linked.discard(run_id)

    def _claim(self, data: Run) -> Any:
        """Take the library's existing trial for a warm-start run.

        Returns:
            The run id of the run's still-running trial, `_FINISHED` if its
            trial already finished, or None if the library has none.
        """
        if self._warm_start_over:
            return None
        if self._index is None:
            self._index = self._build_index()
        index = self._index
        if data.wandb_run_id in index.finished_runs:
            index.finished_runs.discard(data.wandb_run_id)
            return _FINISHED
        run_id = index.running_by_run.pop(data.wandb_run_id, None)
        if run_id is not None or not index.unlinked_running:
            return run_id
        config = data.config.flat_dict()
        for i, candidate in enumerate(index.unlinked_running):
            if self._trials.matches(candidate, config):
                return index.unlinked_running.pop(i)
        return None

    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        """Warm-start the library with a run that already stopped.

        A library the caller persisted may already hold the run's trial. A
        finished one is left as is; a running one -- the run ended while no
        scheduler watched it -- is finalized with the run's result. Only a
        run the library has never seen becomes a new trial.

        Args:
            data: The run's final state, summary metrics and history.
        """
        if not is_terminal_state(data.state):
            return
        claimed = self._claim(data)
        if claimed is None:
            self._trials.add_finished(data)
        elif claimed is not _FINISHED:
            self._tell_run(self._trials.resume(claimed), data)

    def tell_existing_active_run(self, data: Run) -> Any:
        """Adopt an in-flight run, resuming its trial if the library has one.

        A library the caller persisted may already hold the run's trial. A
        running one is tracked again under its own run id; a finished one
        already records the run's outcome, so the run is left untracked
        rather than duplicated.

        Args:
            data: The run's config and state.

        Returns:
            The run id to track the run by, or None if the run's trial
            already finished or the library cannot adopt the run.
        """
        claimed = self._claim(data)
        if claimed is _FINISHED:
            return None
        if claimed is None:
            run_id = self._trials.adopt_new(data)
        else:
            run_id = self._trials.resume(claimed)
        if run_id is not None:
            self.link(run_id, data.wandb_run_id)
        return run_id
