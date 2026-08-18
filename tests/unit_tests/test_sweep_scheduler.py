from __future__ import annotations

import abc
import contextlib
import signal
from collections.abc import Iterator, Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from wandb.apis.public import Sweep, SweepState
from wandb.apis.public.service_api import ServiceApi
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
    Scheduler,
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


def make_scheduler_grid_sweep() -> Sweep:
    """Return a grid `Sweep` backed by a no-op `ServiceApi`.

    Passing `attrs` keeps the constructor from issuing a GraphQL load().
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
            "config": yaml.dump(SCHEDULER_GRID_SWEEP_CONFIG),
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
