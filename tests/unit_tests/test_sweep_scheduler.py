from __future__ import annotations

import abc
import contextlib
import signal
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner
from wandb.apis.public import Sweep, SweepState
from wandb.apis.public.service_api import ServiceApi
from wandb.cli import cli
from wandb.errors import CommError
from wandb.proto.wandb_api_pb2 import ApiErrorResponse
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps import SweepNotFoundError
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    Run,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
)
from wandb.sdk.sweeps.scheduler.scheduler import (
    _MAX_CONSECUTIVE_ERRORS,
    Executor,
    InMemoryScheduler,
    Scheduler,
    SchedulerOptions,
    _LoopControl,
    _ShutdownMonitor,
)

SCHEDULER_GRID_SWEEP_CONFIG: dict[str, Any] = {
    "name": "test-sweep-grid-hyperband",
    "method": "grid",
    "early_terminate": {"type": "hyperband", "max_iter": 5, "eta": 2, "s": 2},
    "metric": {"name": "loss", "goal": "minimize"},
    "parameters": {"param1": {"values": [1, 2, 3]}},
    "scheduler": {"engine": "wandb"},
}


def make_scheduler_grid_sweep(config: dict[str, Any] | None = None) -> Sweep:
    """Return a grid `Sweep` backed by a no-op `ServiceApi`.

    Passing `attrs` keeps the constructor from issuing a GraphQL load(). A
    custom `config` overrides the default grid config, e.g. to drive
    `Sweep.config["scheduler"]` variants without hand-rolling a mock.
    """
    service_api = MagicMock(spec=ServiceApi)
    sweep = Sweep(
        service_api=service_api,
        entity="test_entity",
        project="test_project",
        sweep_id="test_sweep",
        attrs={
            "id": "test_sweep",
            "name": "test_sweep",
            "config": yaml.dump(
                SCHEDULER_GRID_SWEEP_CONFIG if config is None else config
            ),
        },
    )
    sweep.finish = MagicMock()  # type: ignore[attr-defined]
    return sweep


def make_run(
    suggestion: RunSuggestion,
    *,
    state: RunState,
    summary: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    wandb_run_id: str = "wandb-run-id",
) -> RunWithMetrics:
    return RunWithMetrics(
        config=suggestion.config,
        state=state,
        wandb_run_id=wandb_run_id,
        summary_metrics=summary,
        history_metrics=history or [],
    )


@dataclass
class RemoteRun:
    """A sweep run as fetched from the W&B API.

    Carries the fields `InMemoryScheduler` reads from `wandb.apis.public.Run`
    when polling or warm-starting.
    """

    id: str
    state: str
    config: dict[str, Any]
    summary_metrics: dict[str, Any] = field(default_factory=dict)
    storage_id: str = ""
    history_metrics: list[dict[str, Any]] = field(default_factory=list)
    history_error: Exception | None = None

    def __post_init__(self) -> None:
        if not self.storage_id:
            self.storage_id = self.id

    def history(
        self,
        keys: list[str] | None = None,
        samples: int | None = None,
        pandas: bool = False,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Return sampled history rows, like `wandb.apis.public.Run.history`.

        `history_error` stands in for that per-run query failing.
        """
        if self.history_error is not None:
            raise self.history_error
        return list(self.history_metrics)


def make_remote_run(
    run_id: str,
    state: RunState | str,
    config: dict[str, Any],
    summary: dict[str, Any] | None = None,
    *,
    storage_id: str | None = None,
    history: list[dict[str, Any]] | None = None,
    history_error: Exception | None = None,
) -> RemoteRun:
    """Build a `RemoteRun` for tests or stubs of `Api.runs()` results."""
    state_str = state.value if isinstance(state, RunState) else state
    return RemoteRun(
        id=run_id,
        state=state_str,
        config=config,
        summary_metrics=summary or {},
        storage_id=storage_id or "",
        history_metrics=history or [],
        history_error=history_error,
    )


def api_error(status: int | None = None, message: str = "boom") -> WandbApiFailedError:
    """A W&B API failure as wandb-core reports it.

    Args:
        status: The upstream HTTP status. None models a failure that never
            reached an HTTP response.
        message: The failure message.
    """
    if status is None:
        return WandbApiFailedError(message)
    return WandbApiFailedError(
        message,
        ApiErrorResponse(message=message, http_status=status),
    )


class StateSource:
    """Serve a scripted sequence of sweep-state reads.

    Each entry is a `SweepState` to return or an exception to raise. The last
    entry repeats, so a test needn't predict how often the loop reads.
    """

    def __init__(self, *entries: SweepState | BaseException) -> None:
        self.entries = entries
        self.calls = 0

    def __call__(self) -> SweepState:
        self.calls += 1
        entry = self.entries[min(self.calls - 1, len(self.entries) - 1)]
        if isinstance(entry, BaseException):
            raise entry
        return entry


def make_suggestions(n: int, prefix: str = "opt") -> list[RunSuggestion]:
    return [
        RunSuggestion(
            config=RunConfig.from_values({"param1": i + 1}),
            run_id=f"{prefix}-{i}",
        )
        for i in range(n)
    ]


class MockOptimizer(Optimizer):
    """Minimal optimizer with mockable hooks for scheduler contract tests."""

    def __init__(self, sweep: Sweep) -> None:
        super().__init__(sweep)
        self.ask_n_runs_mock = MagicMock(side_effect=lambda n: make_suggestions(n))
        self.tell_run_mock = MagicMock()
        self.tell_existing_finished_run_mock = MagicMock()
        self.tell_existing_active_run_mock = MagicMock(
            side_effect=lambda data: f"adopted-{data.wandb_run_id}"
        )
        self.prune_runs_mock = MagicMock(return_value=[])
        self.should_terminate_sweep_mock = MagicMock(return_value=False)

    def ask_n_runs(self, n: int) -> Sequence[RunSuggestion]:
        return self.ask_n_runs_mock(n)

    def tell_run(self, run_id: Any, data: RunWithMetrics) -> None:
        self.tell_run_mock(run_id, data)

    def tell_existing_finished_run(self, data: RunWithMetrics) -> None:
        self.tell_existing_finished_run_mock(data)

    def tell_existing_active_run(self, data: Run) -> Any:
        return self.tell_existing_active_run_mock(data)

    def prune_runs(
        self, run_ids: Sequence[str], runs: Sequence[RunWithMetrics]
    ) -> Sequence[str]:
        return self.prune_runs_mock(run_ids, runs)

    def should_terminate_sweep(self) -> bool:
        return self.should_terminate_sweep_mock()


class OptimizerAcceptanceTests(abc.ABC):
    """Contract tests every Optimizer implementation must satisfy."""

    @pytest.fixture
    def sweep(self) -> Sweep:
        return make_scheduler_grid_sweep()

    @abc.abstractmethod
    @pytest.fixture
    def optimizer(self, sweep: Sweep) -> Optimizer:
        """Return a fresh, configured Optimizer instance."""
        ...

    def test_next_2_runs_after_tell_1_run(
        self, optimizer: Optimizer, sweep: Sweep
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
        self, optimizer: Optimizer, sweep: Sweep
    ) -> None:
        first_run = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="run_id"
        )
        run = make_run(first_run, state=RunState.FINISHED, summary={"loss": 1.0})
        optimizer.tell_existing_finished_run(run)
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        assert suggestion.config["param1"].value == 2

    def test_next_run_after_tell_existing_active_run(
        self, optimizer: Optimizer, sweep: Sweep
    ) -> None:
        first_run = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="run_id"
        )
        run = make_run(first_run, state=RunState.RUNNING, summary={"loss": 1.0})
        optimizer.tell_existing_active_run(run)
        suggestion = next(iter(optimizer.ask_n_runs(1)))
        assert suggestion.config["param1"].value == 2

    def test_prune_runs_returns_empty_for_no_candidates(
        self, optimizer: Optimizer
    ) -> None:
        assert optimizer.prune_runs([], []) == []

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
        better_running = make_run(
            suggestions[2],
            state=RunState.RUNNING,
            summary={"loss": 7.0},
            history=[{"loss": 10.0}, {"loss": 7.0}, {"loss": 7.0}],
        )
        optimizer.tell_run(suggestions[1].run_id, worst_running)
        optimizer.tell_run(suggestions[2].run_id, better_running)

        pruned = optimizer.prune_runs(
            [suggestions[1].run_id, suggestions[2].run_id],
            [worst_running, better_running],
        )
        assert pruned == [suggestions[1].run_id]


class TestWandbOptimizerAcceptance(OptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, sweep: Sweep) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.wandb import WandbOptimizer

        return WandbOptimizer(sweep=sweep)


def _make_sequential_sampler(optuna_module: Any) -> Any:
    """A deterministic sampler cycling a categorical param's choices in order.

    Real optuna samplers pick randomly (or per some search strategy), but the
    shared acceptance tests -- written against `WandbOptimizer`'s
    deterministic grid search -- assert an exact suggestion order.
    """

    class _SequentialSampler(optuna_module.samplers.BaseSampler):
        def infer_relative_search_space(self, study: Any, trial: Any) -> dict:
            return {}

        def sample_relative(self, study: Any, trial: Any, search_space: dict) -> dict:
            return {}

        def sample_independent(
            self, study: Any, trial: Any, param_name: str, param_distribution: Any
        ) -> Any:
            choices = list(param_distribution.choices)
            seen = sum(
                1
                for t in study.get_trials(deepcopy=False)
                if t.number != trial.number and param_name in t.params
            )
            return choices[seen % len(choices)]

    return _SequentialSampler()


class OptunaOptimizerAcceptanceTests(OptimizerAcceptanceTests):
    """Shared setup for the Optuna optimizer flavors.

    Overrides the hyperband pruning test: optuna's pruners judge a running
    trial only against *completed*-trial history, unlike the `sweeps`
    library's hyperband, which ranks concurrently running trials against each
    other.
    """

    @pytest.fixture
    def study(self) -> Any:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        return optuna.create_study(
            direction="minimize",
            sampler=_make_sequential_sampler(optuna),
            pruner=optuna.pruners.MedianPruner(n_startup_trials=0, n_warmup_steps=0),
        )

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
        better_running = make_run(
            suggestions[2],
            state=RunState.RUNNING,
            summary={"loss": 5.0},
            history=[{"loss": 10.0}, {"loss": 5.0}, {"loss": 5.0}],
        )
        optimizer.tell_run(suggestions[1].run_id, worst_running)
        optimizer.tell_run(suggestions[2].run_id, better_running)

        pruned = optimizer.prune_runs(
            [suggestions[1].run_id, suggestions[2].run_id],
            [worst_running, better_running],
        )
        assert pruned == [suggestions[1].run_id]


class TestOptunaDeclarativeOptimizerAcceptance(OptunaOptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, study: Any, sweep: Sweep) -> Optimizer:
        import optuna
        from wandb.sdk.sweeps.scheduler.optuna import OptunaDeclarativeOptimizer

        distributions = {
            "param1": optuna.distributions.CategoricalDistribution([1, 2, 3])
        }
        return OptunaDeclarativeOptimizer(study, distributions, sweep)


class TestOptunaImperativeOptimizerAcceptance(OptunaOptimizerAcceptanceTests):
    @pytest.fixture
    def optimizer(self, study: Any, sweep: Sweep) -> Optimizer:
        from wandb.sdk.sweeps.scheduler.optuna import OptunaImperativeOptimizer

        def trial_constructor(trial: Any) -> dict[str, Any]:
            return {"param1": trial.suggest_categorical("param1", [1, 2, 3])}

        return OptunaImperativeOptimizer(study, trial_constructor, sweep)


class TestOptunaOptimizerTermination:
    """`OptunaOptimizer.should_terminate_sweep` and its OptunaHub loading."""

    @pytest.fixture
    def sweep(self) -> Sweep:
        return make_scheduler_grid_sweep()

    @pytest.fixture
    def study(self) -> Any:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        return optuna.create_study(direction="minimize")

    def _make_optimizer(self, study: Any, sweep: Sweep, terminator: Any = None) -> Any:
        import optuna
        from wandb.sdk.sweeps.scheduler.optuna import OptunaDeclarativeOptimizer

        distributions = {"param1": optuna.distributions.IntDistribution(1, 3)}
        return OptunaDeclarativeOptimizer(study, distributions, sweep, terminator)

    def test_no_terminator_never_terminates(self, study: Any, sweep: Sweep) -> None:
        optimizer = self._make_optimizer(study, sweep)
        assert optimizer.should_terminate_sweep() is False

    def test_delegates_to_the_configured_terminator(
        self, study: Any, sweep: Sweep
    ) -> None:
        terminator = MagicMock(return_value=True)
        optimizer = self._make_optimizer(study, sweep, terminator)

        assert optimizer.should_terminate_sweep() is True
        terminator.assert_called_once_with(study)

    def test_a_falsy_terminator_does_not_terminate(
        self, study: Any, sweep: Sweep
    ) -> None:
        terminator = MagicMock(return_value=False)
        optimizer = self._make_optimizer(study, sweep, terminator)

        assert optimizer.should_terminate_sweep() is False
        terminator.assert_called_once_with(study)


class LoopDriver:
    """Drive `Scheduler.loop()` from the loop's own progress.

    Stubbing `sweep_state` with a list of return values ties a test to how many
    times the loop happens to read the state, and says nothing about *when* a
    transition becomes visible. This driver serves whatever state the test last
    set -- the loop may read it as often as it likes -- and only advances at a
    real synchronization point: an iteration completing, or the test setting a
    new state once it knows the loop reached the point under test.

    `max_iterations` doubles as a hang guard: a loop that ignores its exit
    conditions is pushed out with `exit_state` instead of spinning forever.
    """

    def __init__(
        self,
        scheduler: Scheduler,
        state: SweepState = SweepState.RUNNING,
        *,
        max_iterations: int = 1,
        exit_state: SweepState = SweepState.FINISHED,
    ) -> None:
        self._scheduler = scheduler
        self._real_loop_iteration = scheduler._loop_iteration
        self.state = state
        self.max_iterations = max_iterations
        self.exit_state = exit_state
        self.iterations = 0

    @contextlib.contextmanager
    def driving(self) -> Iterator[LoopDriver]:
        """Patch the scheduler so `scheduler.loop()` is driven by this driver."""
        with (
            patch.object(
                self._scheduler, "sweep_state", side_effect=lambda: self.state
            ),
            patch.object(
                self._scheduler, "_loop_iteration", side_effect=self._iteration
            ),
        ):
            yield self

    def _iteration(self) -> _LoopControl:
        self.iterations += 1
        try:
            return self._real_loop_iteration()
        finally:
            if self.iterations >= self.max_iterations:
                self.state = self.exit_state


class SchedulerAcceptanceTests(abc.ABC):
    """Contract tests every Scheduler implementation must satisfy."""

    @pytest.fixture
    def sweep(self) -> Sweep:
        return make_scheduler_grid_sweep()

    @pytest.fixture
    def optimizer(self, sweep: Sweep) -> MockOptimizer:
        return MockOptimizer(sweep=sweep)

    @pytest.fixture
    def batch_size(self) -> int:
        return 2

    @pytest.fixture
    def executor(self) -> MagicMock:
        executor = MagicMock(spec=Executor)
        executor.schedule.side_effect = lambda suggestion: f"wandb-{suggestion.run_id}"
        executor.reap.return_value = set()
        return executor

    @pytest.fixture
    def sleeps(self, monkeypatch: pytest.MonkeyPatch) -> list[float]:
        """Record the loop's poll waits instead of performing them.

        Recording rather than zeroing keeps the slowdown observable.
        """
        recorded: list[float] = []
        monkeypatch.setattr(
            _ShutdownMonitor,
            "wait",
            lambda self, seconds: recorded.append(seconds),
        )
        return recorded

    @abc.abstractmethod
    @pytest.fixture
    def scheduler(
        self,
        optimizer: Optimizer,
        sweep: Sweep,
        executor: MagicMock,
        batch_size: int,
    ) -> Scheduler: ...

    def test_schedule_up_to_batch_size(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        batch_size: int,
    ) -> None:
        assert len(scheduler.in_flight_runs()) == 0
        scheduler.push_in_flight_run("wandb-existing", "opt-existing")
        with patch.object(scheduler, "sweep_state", return_value=SweepState.RUNNING):
            scheduler._schedule_suggestions()

        assert len(scheduler.in_flight_runs()) == batch_size
        assert "wandb-existing" in scheduler.in_flight_runs()
        assert "wandb-opt-0" in scheduler.in_flight_runs()
        optimizer.ask_n_runs_mock.assert_called_once_with(batch_size - 1)

    def test_schedule_then_poll_one_finished(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        mock_api: MagicMock,
        batch_size: int,
    ) -> None:
        with patch.object(scheduler, "sweep_state", return_value=SweepState.RUNNING):
            scheduler._schedule_suggestions()
        assert len(scheduler.in_flight_runs()) == batch_size

        mock_api.runs.return_value = [
            make_remote_run(
                "wandb-opt-0",
                RunState.FINISHED,
                {"param1": 1},
                {"loss": 1.0},
            ),
            make_remote_run(
                "wandb-opt-1",
                RunState.RUNNING,
                {"param1": 2},
                {"loss": 2.0},
            ),
        ]

        scheduler._poll_active_runs()

        tell_calls = {
            call.args[0]: call.args[1]
            for call in optimizer.tell_run_mock.call_args_list
        }
        assert tell_calls["opt-0"].state == RunState.FINISHED
        assert tell_calls["opt-0"].wandb_run_id == "wandb-opt-0"
        assert tell_calls["opt-0"].summary_metrics == {"loss": 1.0}
        assert tell_calls["opt-1"].state == RunState.RUNNING
        assert tell_calls["opt-1"].wandb_run_id == "wandb-opt-1"
        assert tell_calls["opt-1"].summary_metrics == {"loss": 2.0}
        assert len(scheduler.in_flight_runs()) == batch_size - 1
        assert "wandb-opt-1" in scheduler.in_flight_runs()

    def test_warm_start_adopts_existing_runs(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        mock_api: MagicMock,
    ) -> None:
        finished = make_remote_run(
            "existing-finished",
            RunState.FINISHED,
            {"param1": 1},
            {"loss": 0.5},
        )
        active = make_remote_run(
            "existing-active",
            RunState.RUNNING,
            {"param1": 2},
            {"loss": 1.0},
        )

        def runs_side_effect(
            path: str,
            filters: dict[str, Any],
            per_page: int = 50,
            lazy: bool = False,
        ) -> list[RemoteRun]:
            state_filter = filters.get("state")
            if state_filter is not None:
                states = state_filter["$in"]
                if RunState.FINISHED.value in states:
                    return [finished]
                if RunState.RUNNING.value in states:
                    return [active]
            return []

        mock_api.runs.side_effect = runs_side_effect

        scheduler._warm_start()

        optimizer.tell_existing_finished_run_mock.assert_called_once()
        finished_arg = optimizer.tell_existing_finished_run_mock.call_args[0][0]
        assert finished_arg.wandb_run_id == "existing-finished"
        assert finished_arg.state == RunState.FINISHED

        optimizer.tell_existing_active_run_mock.assert_called_once()
        active_arg = optimizer.tell_existing_active_run_mock.call_args[0][0]
        assert active_arg.wandb_run_id == "existing-active"
        assert active_arg.state == RunState.RUNNING

        assert len(scheduler.in_flight_runs()) == 1
        assert "existing-active" in scheduler.in_flight_runs()

    def test_warm_start_raises_when_api_runs_fails(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        mock_api: MagicMock,
    ) -> None:
        mock_api.runs.side_effect = RuntimeError("api unavailable")

        with pytest.raises(RuntimeError, match="api unavailable"):
            scheduler._warm_start()

        optimizer.tell_existing_finished_run_mock.assert_not_called()
        optimizer.tell_existing_active_run_mock.assert_not_called()
        assert len(scheduler.in_flight_runs()) == 0

    def test_poll_handles_deleted_runs(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        mock_api: MagicMock,
    ) -> None:
        scheduler.push_in_flight_run("run-0", "opt-0")
        scheduler.push_in_flight_run("run-1", "opt-1")
        scheduler.push_in_flight_run("run-2", "opt-2")
        assert len(scheduler.in_flight_runs()) == 3

        mock_api.runs.return_value = [
            make_remote_run(
                "run-2",
                RunState.RUNNING,
                {"param1": 3},
                {"loss": 3.0},
            ),
        ]

        scheduler._poll_active_runs()

        assert optimizer.tell_run_mock.call_count == 3
        deleted_calls = [
            call
            for call in optimizer.tell_run_mock.call_args_list
            if call[0][1].state == RunState.FAILED
        ]
        assert len(deleted_calls) == 2
        deleted_ids = {call[0][0] for call in deleted_calls}
        assert deleted_ids == {"opt-0", "opt-1"}

        assert len(scheduler.in_flight_runs()) == 1
        assert "run-2" in scheduler.in_flight_runs()

    def test_prune_active_runs(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        mock_internal_api: MagicMock,
    ) -> None:
        prune_suggestion = RunSuggestion(
            config=RunConfig.from_values({"param1": 1}), run_id="opt-prune"
        )
        keep_suggestion = RunSuggestion(
            config=RunConfig.from_values({"param1": 2}), run_id="opt-keep"
        )
        scheduler.push_in_flight_run("run-prune", "opt-prune")
        scheduler.push_in_flight_run("run-keep", "opt-keep")

        active = [
            make_run(
                prune_suggestion,
                state=RunState.RUNNING,
                summary={"loss": 10.0},
                wandb_run_id="run-prune",
                history=[{"loss": 10.0}, {"loss": 10.0}],
            ),
            make_run(
                keep_suggestion,
                state=RunState.RUNNING,
                summary={"loss": 1.0},
                wandb_run_id="run-keep",
                history=[{"loss": 10.0}, {"loss": 1.0}],
            ),
        ]

        optimizer.prune_runs_mock.return_value = ["opt-prune"]

        if isinstance(scheduler, InMemoryScheduler):
            scheduler._storage_ids["run-prune"] = "storage-prune"

        scheduler._prune_active_runs(active)

        optimizer.prune_runs_mock.assert_called_once_with(
            ["opt-prune", "opt-keep"],
            active,
        )
        assert "run-prune" not in scheduler.in_flight_runs()
        assert "run-keep" in scheduler.in_flight_runs()

    def test_loop_does_nothing_when_paused(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        executor: MagicMock,
        mock_api: MagicMock,
        mock_internal_api: MagicMock,
    ) -> None:
        # Stay paused for two full iterations, then let the sweep finish so the
        # loop exits on its own.
        driver = LoopDriver(scheduler, SweepState.PAUSED, max_iterations=2)
        with driver.driving():
            scheduler.loop()

        assert driver.iterations == 2
        assert len(scheduler.in_flight_runs()) == 0
        executor.schedule.assert_not_called()
        optimizer.ask_n_runs_mock.assert_not_called()
        optimizer.tell_run_mock.assert_not_called()
        assert mock_api.runs.call_count <= 2  # warm-start queries only
        mock_internal_api.stop_run.assert_not_called()

    def test_loop_finishes_sweep_when_optimizer_is_exhausted(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        sweep: Sweep,
        executor: MagicMock,
        batch_size: int,
    ) -> None:
        # Nothing left to propose means the search space is exhausted.
        optimizer.ask_n_runs_mock.side_effect = lambda n: []

        # The sweep stays RUNNING for more iterations than the loop should take,
        # so exhaustion -- not a state transition -- has to end it.
        driver = LoopDriver(scheduler, SweepState.RUNNING, max_iterations=2)
        with driver.driving():
            scheduler.loop()

        assert driver.iterations == 1
        optimizer.ask_n_runs_mock.assert_called_once_with(batch_size)
        sweep.finish.assert_called_once()  # type: ignore[attr-defined]
        executor.schedule.assert_not_called()
        assert len(scheduler.in_flight_runs()) == 0

    def test_loop_keeps_polling_when_optimizer_declines_to_propose(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        sweep: Sweep,
        executor: MagicMock,
        batch_size: int,
    ) -> None:
        # None declines this round (e.g. the strategy is waiting on results);
        # the loop must keep polling instead of finishing the sweep.
        optimizer.ask_n_runs_mock.side_effect = lambda n: None

        driver = LoopDriver(scheduler, SweepState.RUNNING, max_iterations=2)
        with driver.driving():
            scheduler.loop()

        # Only the driver's state transition ends the loop.
        assert driver.iterations == 2
        assert optimizer.ask_n_runs_mock.call_count == 2
        sweep.finish.assert_not_called()  # type: ignore[attr-defined]
        executor.schedule.assert_not_called()
        assert len(scheduler.in_flight_runs()) == 0

    def test_loop_exits_when_cancelled_without_calling_optimizer(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        executor: MagicMock,
        mock_api: MagicMock,
    ) -> None:
        optimizer_called = threading.Event()
        release_optimizer = threading.Event()
        warm_start_runs_calls = 2

        def blocking_next_n(n: int) -> list[RunSuggestion]:
            optimizer_called.set()
            # Block until the test releases it, so the loop must exit while
            # the optimizer is still working. The pytest timeout is the
            # backstop if the loop never exits.
            release_optimizer.wait()
            return make_suggestions(n)

        optimizer.ask_n_runs_mock.side_effect = blocking_next_n

        def guarded_runs(*args: Any, **kwargs: Any) -> list[RemoteRun]:
            if optimizer_called.is_set():
                raise AssertionError(
                    "scheduler fetched run state while optimizer was working"
                )
            return []

        mock_api.runs.side_effect = guarded_runs

        driver = LoopDriver(
            scheduler, SweepState.RUNNING, exit_state=SweepState.CANCELED
        )

        def run_loop() -> None:
            with driver.driving():
                scheduler.loop()

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(run_loop)
                # Cancel only once the optimizer is known to be working, so the
                # loop has to notice the transition while blocked on
                # `ask_n_runs` rather than at some particular state query.
                optimizer_called.wait()
                driver.state = SweepState.CANCELED
                # Re-raises anything the loop raised, including guarded_runs's
                # AssertionError.
                future.result()
        finally:
            # Unblock the optimizer's fetch thread before asserting.
            release_optimizer.set()

        optimizer.ask_n_runs_mock.assert_called_once()
        # The loop left without waiting for the blocked optimizer, so nothing
        # it would eventually suggest was scheduled.
        executor.schedule.assert_not_called()
        assert len(scheduler.in_flight_runs()) == 0
        assert mock_api.runs.call_count == warm_start_runs_calls

    def test_loop_exits_when_sweep_state_not_found(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
    ) -> None:
        with patch.object(
            scheduler,
            "sweep_state",
            side_effect=CommError("sweep not found"),
        ):
            with pytest.raises(CommError, match="sweep not found"):
                scheduler.loop()

        optimizer.ask_n_runs_mock.assert_not_called()

    @pytest.mark.parametrize(
        "status",
        [None, 0, 408, 500, 502, 503, 504],
    )
    def test_loop_keeps_polling_through_intermittent_api_error(
        self,
        scheduler: Scheduler,
        sleeps: list[float],
        status: int | None,
    ) -> None:
        """A transient failure reading sweep state must not end the sweep."""
        source = StateSource(
            api_error(status),
            SweepState.RUNNING,
            SweepState.FINISHED,
        )
        iterations = 0

        def iteration() -> _LoopControl:
            nonlocal iterations
            iterations += 1
            return _LoopControl.CONTINUE

        with (
            patch.object(scheduler, "sweep_state", side_effect=source),
            patch.object(scheduler, "_loop_iteration", side_effect=iteration),
        ):
            scheduler.loop()

        # Absorbed rather than raised, so a real iteration still ran.
        assert iterations == 1
        assert sleeps == [1.0, 0.0]  # slowed down, then back to the poll rate

    @pytest.mark.parametrize(
        "status",
        [400, 401, 403, 409, 410, 413, 422, 501],
    )
    def test_loop_exits_immediately_on_permanent_api_error(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
        sleeps: list[float],
        status: int,
    ) -> None:
        error = api_error(status)
        with patch.object(scheduler, "sweep_state", side_effect=StateSource(error)):
            with pytest.raises(WandbApiFailedError):
                scheduler.loop()

        assert sleeps == []  # exited without waiting
        optimizer.ask_n_runs_mock.assert_not_called()

    def test_loop_exits_immediately_when_sweep_is_gone(
        self,
        scheduler: Scheduler,
        sleeps: list[float],
    ) -> None:
        """A 404 ends the loop rather than being retried."""
        error = api_error(404)
        with patch.object(scheduler, "sweep_state", side_effect=StateSource(error)):
            with pytest.raises(WandbApiFailedError):
                scheduler.loop()

        assert sleeps == []

    def test_loop_exits_immediately_when_sweep_query_returns_no_sweep(
        self,
        scheduler: Scheduler,
        sleeps: list[float],
    ) -> None:
        """A deleted sweep raises `SweepNotFoundError`, not a 404."""
        error = SweepNotFoundError("Could not find sweep <Sweep e/p/s>")
        with patch.object(scheduler, "sweep_state", side_effect=StateSource(error)):
            with pytest.raises(SweepNotFoundError, match="Could not find sweep"):
                scheduler.loop()

        assert sleeps == []

    def test_loop_slows_down_while_rate_limited_without_giving_up(
        self,
        scheduler: Scheduler,
        sleeps: list[float],
    ) -> None:
        """Throttling slows polling indefinitely; it never ends the sweep."""
        throttled = [api_error(429)] * (_MAX_CONSECUTIVE_ERRORS + 5)
        source = StateSource(*throttled, SweepState.FINISHED)

        with patch.object(scheduler, "sweep_state", side_effect=source):
            scheduler.loop()

        assert len(sleeps) == len(throttled)
        assert sleeps[:4] == [1.0, 2.0, 4.0, 8.0]  # doubles up to the cap
        assert sleeps[-1] == 60.0
        assert sleeps == sorted(sleeps)

    def test_loop_gives_up_after_repeated_failed_polls(
        self,
        scheduler: Scheduler,
        sleeps: list[float],
    ) -> None:
        """A backend that never recovers ends the loop instead of spinning."""
        error = api_error(503)
        with patch.object(scheduler, "sweep_state", side_effect=StateSource(error)):
            with pytest.raises(WandbApiFailedError):
                scheduler.loop()

        assert len(sleeps) == _MAX_CONSECUTIVE_ERRORS

    def test_loop_returns_to_normal_poll_rate_after_a_clean_iteration(
        self,
        scheduler: Scheduler,
        sleeps: list[float],
    ) -> None:
        source = StateSource(
            api_error(503),
            SweepState.RUNNING,
            api_error(503),
            SweepState.FINISHED,
        )
        with (
            patch.object(scheduler, "sweep_state", side_effect=source),
            patch.object(
                scheduler,
                "_loop_iteration",
                return_value=_LoopControl.CONTINUE,
            ),
        ):
            scheduler.loop()

        assert sleeps == [1.0, 0.0, 1.0]  # without the reset, 2.0 at the end

    def test_loop_reads_sweep_state_once_per_iteration(
        self,
        scheduler: Scheduler,
    ) -> None:
        """Each read is a full sweep query, so the loop makes one per pass."""
        source = StateSource(
            SweepState.RUNNING,
            SweepState.RUNNING,
            SweepState.FINISHED,
        )
        with (
            patch.object(scheduler, "sweep_state", side_effect=source),
            patch.object(
                scheduler,
                "_loop_iteration",
                return_value=_LoopControl.CONTINUE,
            ),
        ):
            scheduler.loop()

        # Two iterations plus the read that ended the loop, none after.
        assert source.calls == 3

    def test_loop_finishes_iteration_on_shutdown_signal(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
    ) -> None:
        call_order: list[str] = []

        def poll_with_shutdown() -> list[RunWithMetrics]:
            call_order.append("poll")
            scheduler._shutdown.handle_signal(signal.SIGTERM, None)
            return []

        # The sweep stays RUNNING for more iterations than the loop should take:
        # the shutdown request, not a state transition, has to end it after the
        # iteration in flight completes.
        driver = LoopDriver(scheduler, SweepState.RUNNING, max_iterations=2)

        with (
            driver.driving(),
            patch.object(
                scheduler, "_poll_active_runs", side_effect=poll_with_shutdown
            ),
            patch.object(
                scheduler,
                "_prune_active_runs",
                side_effect=lambda *a, **kw: call_order.append("prune"),
            ),
            patch.object(
                scheduler,
                "_reap_dead_runs",
                side_effect=lambda: call_order.append("reap"),
            ),
            patch.object(
                scheduler,
                "_schedule_suggestions",
                side_effect=lambda: call_order.append("schedule"),
            ),
        ):
            scheduler.loop()

        assert driver.iterations == 1
        assert call_order == ["poll", "prune", "reap", "schedule"]

    def test_loop_finishes_iteration_on_keyboard_interrupt(
        self,
        scheduler: Scheduler,
        optimizer: MockOptimizer,
    ) -> None:
        call_order: list[str] = []

        def poll_with_interrupt() -> list[RunWithMetrics]:
            call_order.append("poll")
            scheduler._shutdown.handle_signal(signal.SIGINT, None)
            return []

        # The sweep stays RUNNING for more iterations than the loop should take:
        # the interrupt, not a state transition, has to end it after the
        # iteration in flight completes.
        driver = LoopDriver(scheduler, SweepState.RUNNING, max_iterations=2)

        with (
            driver.driving(),
            patch.object(
                scheduler, "_poll_active_runs", side_effect=poll_with_interrupt
            ),
            patch.object(
                scheduler,
                "_prune_active_runs",
                side_effect=lambda *a, **kw: call_order.append("prune"),
            ),
            patch.object(
                scheduler,
                "_reap_dead_runs",
                side_effect=lambda: call_order.append("reap"),
            ),
            patch.object(
                scheduler,
                "_schedule_suggestions",
                side_effect=lambda: call_order.append("schedule"),
            ),
        ):
            scheduler.loop()

        assert driver.iterations == 1
        assert call_order == ["poll", "prune", "reap", "schedule"]


class TestInMemorySchedulerAcceptance(SchedulerAcceptanceTests):
    @pytest.fixture
    def mock_api(self) -> Iterator[MagicMock]:
        api = MagicMock()
        api.runs.return_value = []
        with patch("wandb.sdk.sweeps.scheduler.scheduler.Api", return_value=api):
            yield api

    @pytest.fixture
    def mock_internal_api(self) -> Iterator[MagicMock]:
        internal_api = MagicMock()
        internal_api.stop_run.return_value = True
        with patch(
            "wandb.sdk.sweeps.scheduler.scheduler.InternalApi",
            return_value=internal_api,
        ):
            yield internal_api

    @pytest.fixture
    def scheduler(
        self,
        optimizer: Optimizer,
        sweep: Sweep,
        executor: MagicMock,
        mock_api: MagicMock,
        batch_size: int,
    ) -> InMemoryScheduler:
        return InMemoryScheduler(
            optimizer=optimizer,
            sweep=sweep,
            options=SchedulerOptions(
                poll_interval_s=0,
                batch_size=batch_size,
                executor=executor,
            ),
        )

    def test_poll_skips_unreadable_run_and_keeps_the_rest(
        self,
        scheduler: InMemoryScheduler,
        optimizer: MockOptimizer,
        mock_api: MagicMock,
    ) -> None:
        """One run's metrics failing must not cost the whole poll."""
        scheduler.push_in_flight_run("run-ok", "opt-ok")
        scheduler.push_in_flight_run("run-bad", "opt-bad")
        mock_api.runs.return_value = [
            make_remote_run("run-ok", RunState.RUNNING, {"param1": 1}, {"loss": 1.0}),
            make_remote_run(
                "run-bad",
                RunState.RUNNING,
                {"param1": 2},
                history_error=CommError("history query failed"),
            ),
        ]

        scheduler._poll_active_runs()

        told = {call.args[0] for call in optimizer.tell_run_mock.call_args_list}
        assert told == {"opt-ok"}
        # Still on the server, so it stays in flight instead of being failed.
        assert "run-bad" in scheduler.in_flight_runs()
        assert scheduler.unreadable_run_ids() == frozenset({"run-bad"})

    def test_poll_reaps_deleted_run_but_not_unreadable_one(
        self,
        scheduler: InMemoryScheduler,
        optimizer: MockOptimizer,
        mock_api: MagicMock,
    ) -> None:
        """Absent from the server is failed; present but unreadable is not."""
        scheduler.push_in_flight_run("run-deleted", "opt-deleted")
        scheduler.push_in_flight_run("run-bad", "opt-bad")
        mock_api.runs.return_value = [
            make_remote_run(
                "run-bad",
                RunState.RUNNING,
                {"param1": 2},
                history_error=CommError("history query failed"),
            ),
        ]

        scheduler._poll_active_runs()

        failed = {
            call.args[0]
            for call in optimizer.tell_run_mock.call_args_list
            if call.args[1].state == RunState.FAILED
        }
        assert failed == {"opt-deleted"}
        assert "run-deleted" not in scheduler.in_flight_runs()
        assert "run-bad" in scheduler.in_flight_runs()

    def test_failed_poll_keeps_the_storage_ids_pruning_needs(
        self,
        scheduler: InMemoryScheduler,
        mock_api: MagicMock,
        mock_internal_api: MagicMock,
    ) -> None:
        """A failed poll must not strand in-flight runs with no way to stop them."""
        scheduler.push_in_flight_run("run-0", "opt-0")
        mock_api.runs.return_value = [
            make_remote_run(
                "run-0",
                RunState.RUNNING,
                {"param1": 1},
                {"loss": 1.0},
                storage_id="storage-0",
            ),
        ]
        scheduler._poll_active_runs()

        mock_api.runs.side_effect = api_error(503)
        with pytest.raises(WandbApiFailedError):
            scheduler._poll_active_runs()

        # The last good poll's ids survive, so the run is still stoppable.
        assert scheduler.stop_run("run-0")
        mock_internal_api.stop_run.assert_called_once_with("storage-0")

    def test_poll_forgets_storage_ids_when_nothing_is_in_flight(
        self,
        scheduler: InMemoryScheduler,
        mock_api: MagicMock,
    ) -> None:
        scheduler.push_in_flight_run("run-0", "opt-0")
        mock_api.runs.return_value = [
            make_remote_run(
                "run-0",
                RunState.FINISHED,
                {"param1": 1},
                {"loss": 1.0},
                storage_id="storage-0",
            ),
        ]
        scheduler._poll_active_runs()
        assert not scheduler.in_flight_runs()

        scheduler.fetch_active_runs()

        assert not scheduler.stop_run("run-0")
        assert scheduler.unreadable_run_ids() == frozenset()

    def test_every_run_query_prefetches_config_and_summary_metrics(
        self,
        scheduler: InMemoryScheduler,
        mock_api: MagicMock,
    ) -> None:
        """Lazily loaded runs would cost a query per run on first access."""
        scheduler.push_in_flight_run("run-0", "opt-0")
        mock_api.runs.return_value = []

        scheduler.fetch_active_runs()
        scheduler._warm_start()

        assert mock_api.runs.call_count == 3  # one active poll, two warm-start
        for call in mock_api.runs.call_args_list:
            assert call.kwargs["lazy"] is False


@dataclass
class CliSchedulerMocks:
    """Collaborators `sweep_scheduler` talks to, patched for one test."""

    public_api: MagicMock
    scheduler: MagicMock
    resume_sweep: MagicMock
    login: MagicMock


@contextlib.contextmanager
def _cli_scheduler_context(
    sweep: Sweep, *, authenticated: bool = True
) -> Iterator[CliSchedulerMocks]:
    public_api = MagicMock()
    public_api.sweep.return_value = sweep
    scheduler = MagicMock()

    with (
        patch.object(
            cli,
            "_get_cling_api",
            return_value=MagicMock(is_authenticated=authenticated),
        ),
        patch.object(cli, "PublicApi", return_value=public_api),
        patch.object(cli, "login") as login,
        patch(
            "wandb.sdk.sweeps.scheduler.wandb.resume_sweep",
            return_value=scheduler,
        ) as resume_sweep,
    ):
        yield CliSchedulerMocks(
            public_api=public_api,
            scheduler=scheduler,
            resume_sweep=resume_sweep,
            login=login,
        )


def test_sweep_scheduler_cli_resolves_full_sweep_path(runner: CliRunner) -> None:
    sweep = make_scheduler_grid_sweep()
    with _cli_scheduler_context(sweep) as mocks:
        result = runner.invoke(cli.sweep_scheduler, ["entity/project/sweep-1"])

    assert result.exit_code == 0, result.output
    mocks.public_api.sweep.assert_called_once_with("entity/project/sweep-1")
    mocks.resume_sweep.assert_called_once_with(
        sweep, options=SchedulerOptions(poll_interval_s=10.0, batch_size=10)
    )
    mocks.scheduler.loop.assert_called_once()


def test_sweep_scheduler_cli_builds_path_from_entity_and_project(
    runner: CliRunner,
) -> None:
    sweep = make_scheduler_grid_sweep()
    with _cli_scheduler_context(sweep) as mocks:
        result = runner.invoke(
            cli.sweep_scheduler,
            ["--entity", "my-entity", "--project", "my-project", "sweep-1"],
        )

    assert result.exit_code == 0, result.output
    mocks.public_api.sweep.assert_called_once_with("my-entity/my-project/sweep-1")


def test_sweep_scheduler_cli_passes_batch_size_and_poll_interval(
    runner: CliRunner,
) -> None:
    sweep = make_scheduler_grid_sweep()
    with _cli_scheduler_context(sweep) as mocks:
        result = runner.invoke(
            cli.sweep_scheduler,
            ["--batch-size", "7", "--poll-interval", "15.0", "entity/project/sweep-1"],
        )

    assert result.exit_code == 0, result.output
    mocks.resume_sweep.assert_called_once_with(
        sweep, options=SchedulerOptions(poll_interval_s=15.0, batch_size=7)
    )


def test_sweep_scheduler_cli_requires_engine_config(runner: CliRunner) -> None:
    sweep = make_scheduler_grid_sweep(config={})
    with _cli_scheduler_context(sweep) as mocks:
        result = runner.invoke(cli.sweep_scheduler, ["entity/project/sweep-1"])

    assert result.exit_code != 0
    assert "requires a sweep created with" in result.output
    mocks.resume_sweep.assert_not_called()


def test_sweep_scheduler_cli_rejects_unsupported_engine(runner: CliRunner) -> None:
    sweep = make_scheduler_grid_sweep(
        config={**SCHEDULER_GRID_SWEEP_CONFIG, "scheduler": {"engine": "unknown"}}
    )
    with _cli_scheduler_context(sweep) as mocks:
        result = runner.invoke(cli.sweep_scheduler, ["entity/project/sweep-1"])

    assert result.exit_code != 0
    assert "Unsupported engine: unknown" in result.output
    mocks.resume_sweep.assert_not_called()


def test_sweep_scheduler_cli_warns_when_optimizer_configured(
    runner: CliRunner,
) -> None:
    sweep = make_scheduler_grid_sweep(
        config={
            **SCHEDULER_GRID_SWEEP_CONFIG,
            "scheduler": {"engine": "wandb", "optimizer": "make_optimizer"},
        }
    )
    with _cli_scheduler_context(sweep) as mocks, patch("wandb.termwarn") as termwarn:
        result = runner.invoke(cli.sweep_scheduler, ["entity/project/sweep-1"])

    assert result.exit_code == 0, result.output
    assert any(
        "optimizer config is not supported" in call.args[0]
        for call in termwarn.call_args_list
    )
    mocks.scheduler.loop.assert_called_once()


def test_sweep_scheduler_cli_warns_when_search_space_configured(
    runner: CliRunner,
) -> None:
    sweep = make_scheduler_grid_sweep(
        config={
            **SCHEDULER_GRID_SWEEP_CONFIG,
            "scheduler": {"engine": "wandb", "search_space": "unknown"},
        }
    )
    with _cli_scheduler_context(sweep) as mocks, patch("wandb.termwarn") as termwarn:
        result = runner.invoke(cli.sweep_scheduler, ["entity/project/sweep-1"])

    assert result.exit_code == 0, result.output
    assert any(
        "search_space config is not supported" in call.args[0]
        for call in termwarn.call_args_list
    )
    mocks.scheduler.loop.assert_called_once()


def test_sweep_scheduler_cli_triggers_login_when_unauthenticated(
    runner: CliRunner,
) -> None:
    sweep = make_scheduler_grid_sweep()
    with _cli_scheduler_context(sweep, authenticated=False) as mocks:
        result = runner.invoke(cli.sweep_scheduler, ["entity/project/sweep-1"])

    assert result.exit_code == 0, result.output
    mocks.login.assert_called_once_with(no_offline=True)
