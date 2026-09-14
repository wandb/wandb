from __future__ import annotations

import abc
from typing import Any

import pytest
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

SCHEDULER_GRID_SWEEP_CONFIG: dict[str, Any] = {
    "name": "test-sweep-grid-hyperband",
    "method": "grid",
    "early_terminate": {"type": "hyperband", "max_iter": 5, "eta": 2, "s": 2},
    "metric": {"name": "loss", "goal": "minimize"},
    "parameters": {"param1": {"values": [1, 2, 3]}},
}


def make_scheduler_grid_sweep() -> SweepInfo:
    """Return the `SweepInfo` of a grid sweep with hyperband early termination."""
    return SweepInfo(
        id="test_sweep",
        name="test_sweep",
        entity="test_entity",
        project="test_project",
        config=SCHEDULER_GRID_SWEEP_CONFIG,
    )


def make_run(
    suggestion: RunSuggestion,
    *,
    state: RunState,
    summary: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> RunWithMetrics:
    return RunWithMetrics(
        config=suggestion.config,
        state=state,
        wandb_run_id="wandb-run-id",
        summary_metrics=summary,
        history_metrics=history or [],
    )


class OptimizerAcceptanceTests(abc.ABC):
    """Contract tests every Optimizer implementation must satisfy."""

    @pytest.fixture
    def sweep(self) -> SweepInfo:
        return make_scheduler_grid_sweep()

    @abc.abstractmethod
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        """Return a fresh, configured Optimizer instance."""
        ...

    def test_next_2_runs_after_tell_1_run(
        self, optimizer: Optimizer, sweep: SweepInfo
    ) -> None:
        first_run = next(iter(optimizer.ask_n_runs(1)))
        run = make_run(first_run, state=RunState.FINISHED, summary={"loss": 1.0})
        optimizer.tell_run(first_run.run_id, run)
        suggestions = optimizer.ask_n_runs(2)
        assert len(suggestions) == 2
        assert all(isinstance(s, RunSuggestion) for s in suggestions)
        assert len({s.run_id for s in suggestions}) == 2  # unique ids
        assert suggestions[0].config["param1"].value == 2
        assert suggestions[1].config["param1"].value == 3

    def test_next_run_after_tell_existing_finished_run(
        self, optimizer: Optimizer, sweep: SweepInfo
    ) -> None:
        first_run = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="run_id"
        )
        run = make_run(first_run, state=RunState.FINISHED, summary={"loss": 1.0})
        optimizer.tell_existing_finished_run(run)
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        assert suggestion.config["param1"].value == 2

    def test_next_run_after_tell_existing_active_run(
        self, optimizer: Optimizer, sweep: SweepInfo
    ) -> None:
        first_run = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="run_id"
        )
        run = make_run(first_run, state=RunState.RUNNING, summary={"loss": 1.0})
        optimizer.tell_existing_active_run(run)
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        assert suggestion.config["param1"].value == 2

    def test_ids_unique_across_ask_and_adopt(self, optimizer: Optimizer) -> None:
        """Adoptions and suggestions must never share an id.

        The scheduler routes tells and prunes by id alone, so a collision
        would silently cross-wire two runs.
        """
        adopted = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="run_id"
        )
        run = make_run(adopted, state=RunState.RUNNING, summary={})
        adopted_id = optimizer.tell_existing_active_run(run)
        suggestions = optimizer.ask_n_runs(2)
        ids = [s.run_id for s in suggestions]
        if adopted_id is not None:
            ids.append(adopted_id)
        assert len(set(ids)) == len(ids)

    def test_forget_run_then_ask_still_works(self, optimizer: Optimizer) -> None:
        """Forgetting a suggestion must not corrupt the search state."""
        first_run = next(iter(optimizer.ask_n_runs(1)))
        optimizer.forget_run(first_run.run_id)
        suggestions = optimizer.ask_n_runs(1)
        assert suggestions is None or len(suggestions) <= 1

    def test_prune_runs_returns_empty_for_no_candidates(
        self, optimizer: Optimizer
    ) -> None:
        assert optimizer.prune_runs([], []) == []

    # The better running run's final loss. Low enough that the pruner
    # under test spares that run; subclasses lower it for stricter
    # pruners.
    better_running_loss = 7.0

    def test_prune_runs_hyperband_stops_worst_running_run(
        self, optimizer: Optimizer
    ) -> None:
        suggestions = optimizer.ask_n_runs(3)
        assert len(suggestions) == 3

        optimizer.tell_run(
            suggestions[0].run_id,
            make_run(
                suggestions[0],
                state=RunState.FINISHED,
                summary={"loss": 6.0},
                history=[{"loss": 10.0}, {"loss": 6.0}, {"loss": 6.0}],
            ),
        )
        worst_running = make_run(
            suggestions[1],
            state=RunState.RUNNING,
            summary={"loss": 10.0},
            history=[{"loss": 10.0}, {"loss": 10.0}],
        )
        loss = self.better_running_loss
        better_running = make_run(
            suggestions[2],
            state=RunState.RUNNING,
            summary={"loss": loss},
            history=[{"loss": 10.0}, {"loss": loss}, {"loss": loss}],
        )
        optimizer.tell_run(suggestions[1].run_id, worst_running)
        optimizer.tell_run(suggestions[2].run_id, better_running)

        pruned = optimizer.prune_runs(
            [suggestions[1].run_id, suggestions[2].run_id],
            [worst_running, better_running],
        )
        assert pruned == [suggestions[1].run_id]

    def test_terminal_tell_after_prune_is_noop(self, optimizer: Optimizer) -> None:
        """A pruned run's terminal tell (and a repeated prune) must not raise.

        The scheduler stops a pruned run asynchronously, so the optimizer
        sees the run's terminal state on a later poll — after it may have
        already finalized the run at prune time.
        """
        suggestions = optimizer.ask_n_runs(3)
        runs = []
        for i, suggestion in enumerate(suggestions):
            run = make_run(
                suggestion,
                state=RunState.RUNNING,
                summary={"loss": float(10 * (i + 1))},
                history=[{"loss": float(10 * (i + 1))}] * 2,
            )
            optimizer.tell_run(suggestion.run_id, run)
            runs.append(run)
        run_ids = [s.run_id for s in suggestions]

        pruned = list(optimizer.prune_runs(run_ids, runs))
        for run_id, suggestion in zip(run_ids, suggestions, strict=True):
            if run_id not in pruned:
                continue
            optimizer.tell_run(
                run_id,
                make_run(suggestion, state=RunState.KILLED, summary={}),
            )
        # Offering an already-pruned id again must be tolerated.
        repruned = optimizer.prune_runs(run_ids, runs)
        assert set(repruned) <= set(run_ids)


class TestWandbOptimizerAcceptance(OptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.wandb import WandbOptimizer

        return WandbOptimizer(sweep=sweep)

    def test_forget_run_reproposes_grid_point(self, optimizer: Optimizer) -> None:
        """Forgetting deletes the sample, so grid offers the point again."""
        first_run = next(iter(optimizer.ask_n_runs(1)))
        first_value = first_run.config["param1"].value
        optimizer.forget_run(first_run.run_id)
        again = next(iter(optimizer.ask_n_runs(1)))
        assert again.config["param1"].value == first_value
