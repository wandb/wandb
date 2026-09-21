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


def make_scheduler_grid_sweep(config: dict[str, Any] | None = None) -> SweepInfo:
    """Return the `SweepInfo` of a grid sweep with hyperband early termination.

    Args:
        config: An override for the sweep's config.
    """
    return SweepInfo(
        id="test_sweep",
        name="test_sweep",
        entity="test_entity",
        project="test_project",
        config=SCHEDULER_GRID_SWEEP_CONFIG if config is None else config,
    )


MULTI_OBJECTIVE_SWEEP_CONFIG: dict[str, Any] = {
    "metrics": [
        {"name": "loss", "goal": "minimize"},
        {"name": "accuracy", "goal": "maximize"},
    ],
    "parameters": {"x": {"min": 0.0, "max": 1.0}},
}


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


class MultiObjectiveOptimizerAcceptanceTests(abc.ABC):
    """Contract tests every Optimizer that accepts `metrics` must satisfy.

    A multi-objective sweep declares a goal per metric, so a run's result
    counts only once every objective is in, and no pruner ranking a single
    value can judge the runs producing them.
    """

    RESULT = {"loss": 0.25, "accuracy": 0.9}

    @pytest.fixture
    def sweep(self) -> SweepInfo:
        return make_scheduler_grid_sweep(config=MULTI_OBJECTIVE_SWEEP_CONFIG)

    @abc.abstractmethod
    @pytest.fixture
    def optimizer(self, sweep: SweepInfo) -> Optimizer:
        """Return an Optimizer searching `sweep`'s two objectives."""
        ...

    @abc.abstractmethod
    def recorded_objectives(self, optimizer: Optimizer) -> list[list[Any] | None]:
        """Return the objective values of each result the optimizer recorded.

        Ordered as recorded, with None for a run it declined to score.

        Args:
            optimizer: The optimizer under test.
        """
        ...

    def finish(
        self, optimizer: Optimizer, suggestion: RunSuggestion, summary: dict[str, Any]
    ) -> None:
        optimizer.tell_run(
            suggestion.run_id,
            make_run(suggestion, state=RunState.FINISHED, summary=summary),
        )

    @pytest.mark.parametrize(
        ("summary", "recorded"),
        [
            ({"loss": 0.25, "accuracy": 0.9}, [[0.25, 0.9]]),
            ({"loss": 0.25}, [None]),
        ],
        ids=["every_objective", "missing_an_objective"],
    )
    def test_a_result_counts_only_with_every_objective(
        self,
        optimizer: Optimizer,
        summary: dict[str, Any],
        recorded: list[list[Any] | None],
    ) -> None:
        suggestion = next(iter(optimizer.ask_n_runs(1)))

        self.finish(optimizer, suggestion, summary)

        assert self.recorded_objectives(optimizer) == recorded

    def test_the_search_continues_after_a_result(self, optimizer: Optimizer) -> None:
        """Nothing is left in flight, so the next ask must propose a run."""
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        self.finish(optimizer, suggestion, self.RESULT)

        assert optimizer.ask_n_runs(1)

    def test_warm_start_records_every_objective(self, optimizer: Optimizer) -> None:
        existing = RunSuggestion(
            config=RunConfig.from_values({"x": 0.25}), run_id="prior"
        )

        optimizer.tell_existing_finished_run(
            make_run(existing, state=RunState.FINISHED, summary=self.RESULT)
        )

        assert self.recorded_objectives(optimizer) == [[0.25, 0.9]]

    def test_pruning_never_stops_a_run(self, optimizer: Optimizer) -> None:
        """Pruners rank one value, so they cannot judge a Pareto front."""
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        run = make_run(
            suggestion,
            state=RunState.RUNNING,
            summary={"loss": 9.0, "accuracy": 0.1},
            history=[{"loss": 9.0, "accuracy": 0.1, "_step": 0}],
        )
        optimizer.tell_run(suggestion.run_id, run)

        assert optimizer.prune_runs([suggestion.run_id], [run]) == []


class TestObjectiveMetrics:
    """The base Optimizer reads its objectives from `metric` or `metrics`."""

    def make_optimizer(self, config: dict[str, Any]) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.wandb import WandbOptimizer

        return WandbOptimizer(sweep=make_scheduler_grid_sweep(config=config))

    @pytest.mark.parametrize(
        ("config", "names", "goals"),
        [
            (SCHEDULER_GRID_SWEEP_CONFIG, ["loss"], ["minimize"]),
            (
                MULTI_OBJECTIVE_SWEEP_CONFIG,
                ["loss", "accuracy"],
                ["minimize", "maximize"],
            ),
        ],
        ids=["metric", "metrics"],
    )
    def test_names_and_goals_keep_the_declaration_order(
        self, config: dict[str, Any], names: list[str], goals: list[str]
    ) -> None:
        optimizer = self.make_optimizer(config)

        assert optimizer.metric_names() == names
        assert optimizer.metric_goals() == goals

    @pytest.mark.parametrize(
        ("summary", "values"),
        [
            ({"loss": 1.0, "accuracy": 0.5}, [1.0, 0.5]),
            ({"loss": 1.0}, None),
            ({}, None),
        ],
        ids=["every_objective", "missing_an_objective", "nothing_logged"],
    )
    def test_objective_values_needs_every_objective(
        self, summary: dict[str, Any], values: list[Any] | None
    ) -> None:
        optimizer = self.make_optimizer(MULTI_OBJECTIVE_SWEEP_CONFIG)

        assert optimizer.objective_values(summary) == values


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
