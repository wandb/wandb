from __future__ import annotations

import contextlib
import enum
import select
import signal
import socket
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from wandb import termerror, termlog, termwarn
from wandb.apis.public import Sweep, SweepState
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.failure_policy import Disposition, classify
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    Run,
    RunConfig,
    RunSuggestion,
    RunWithMetrics,
    is_terminal_state,
)
from wandb.wandb_agent import TERMINATING_SIGNALS, ShutdownSignal

_RunT = TypeVar("_RunT", bound=Run)
_T = TypeVar("_T")

# Terminal states, derived from `is_terminal_state` so the two stay in sync.
_TERMINAL_STATES = [s.value for s in RunState if is_terminal_state(s)]

# Sweep states the loop keeps polling for. Anything else ends it.
_ACTIVE_SWEEP_STATES = frozenset(
    {
        SweepState.RUNNING,
        SweepState.PENDING,
        SweepState.PAUSED,
    }
)

# How much longer to wait between polls once W&B calls start failing. This
# throttles the whole loop -- a failed call is never re-issued, since
# wandb-core already retried it; the next poll just happens later, so an
# unhealthy or throttling backend receives fewer requests per minute. The delay
# is added to `poll_interval_s` (absolute, so a `poll_interval_s` of 0 still
# slows down) and doubles per consecutive failed poll.
_INITIAL_SLOWDOWN_S = 1.0
_MAX_SLOWDOWN_S = 60.0

# Consecutive failed polls to absorb before giving up on the sweep. Rate
# limiting doesn't count toward this.
_MAX_CONSECUTIVE_ERRORS = 10


class _LoopControl(enum.Enum):
    CONTINUE = enum.auto()
    TERMINATE = enum.auto()


class Executor(ABC):
    """The backend that starts a suggested run and reports on it later.

    Subclass this to schedule runs somewhere other than the W&B run queue, e.g.
    directly onto SLURM or Volcano. See `WBAgentExecutor` for the default.
    """

    @abstractmethod
    def schedule(self, suggestion: RunSuggestion) -> str:
        """Start or queue a run for `suggestion`; return its W&B run id."""
        ...

    def reap(self, run_ids: Iterable[str]) -> set[str]:
        """Return the `run_ids` whose backend jobs are no longer alive.

        Catches jobs that died before `wandb.init` ran (rejected,
        preempted, crashed at startup) and left their W&B run stuck PENDING.
        """
        return set()


class WBAgentExecutor(Executor):
    """Default executor: enqueue the run into the W&B sweep's run queue.

    A W&B agent (`wandb agent <sweep>`) pulls the queued run and executes it.
    """

    def __init__(self, sweep: Sweep):
        self._sweep = sweep

    def schedule(self, suggestion: RunSuggestion) -> str:
        """Enqueue the run in the sweep's queue; return its W&B run id."""
        return self._sweep.enqueue_run(suggestion.config.wire_dict())


class _ShutdownMonitor:
    """Turn terminating signals into a graceful-shutdown request."""

    def __init__(self) -> None:
        self._requested = False
        self._signum: int | None = None
        self._announced = False
        self._original_handlers: dict[int, Any] = {}
        self._wakeup_recv: socket.socket | None = None
        self._wakeup_send: socket.socket | None = None
        # The wakeup fd this monitor replaced; None while not installed.
        self._prev_wakeup_fd: int | None = None

    @property
    def requested(self) -> bool:
        """Whether a shutdown has been requested (by signal or `request`).

        A read that observes a signal's request also logs the one-time
        acknowledgment, which the signal handler could not do safely.
        """
        if self._requested:
            self._announce()
        return self._requested

    def request(self, signum: int) -> None:
        """Record a shutdown request from normal (non-handler) code."""
        self._signum = signum
        self._requested = True
        self._announce()

    def handle_signal(self, signum: int, frame: Any) -> None:
        """Record a shutdown request; installed as the signal handler.

        Plain attribute writes only to prevent deadlocks
        """
        self._signum = signum
        self._requested = True

    def install(self) -> None:
        """Install the signal handlers and wakeup fd, resetting any request.

        Handlers and the wakeup fd can only be set on the main thread;
        elsewhere they are skipped and `wait` degrades to a full sleep.
        """
        self._requested = False
        self._signum = None
        self._announced = False
        # A socketpair rather than a pipe because on Windows the wakeup fd
        # must be a socket. Non-blocking on both ends so signal delivery
        # never blocks on a full buffer.
        self._wakeup_recv, self._wakeup_send = socket.socketpair()
        self._wakeup_recv.setblocking(False)
        self._wakeup_send.setblocking(False)
        try:
            self._prev_wakeup_fd = signal.set_wakeup_fd(
                self._wakeup_send.fileno(), warn_on_full_buffer=False
            )
        except ValueError:  # not the main thread
            self._prev_wakeup_fd = None

        shutdown_signals = TERMINATING_SIGNALS | {signal.SIGINT}
        for signum in signal.valid_signals() & shutdown_signals:
            with contextlib.suppress(OSError, ValueError):
                self._original_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, self.handle_signal)

    def restore(self) -> None:
        """Undo `install`: put back the prior handlers and wakeup fd."""
        for signum, handler in self._original_handlers.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(signum, handler)
        self._original_handlers.clear()
        if self._prev_wakeup_fd is not None:
            with contextlib.suppress(ValueError):
                signal.set_wakeup_fd(self._prev_wakeup_fd)
            self._prev_wakeup_fd = None
        for sock in (self._wakeup_recv, self._wakeup_send):
            if sock is not None:
                sock.close()
        self._wakeup_recv = None
        self._wakeup_send = None

    def wait(self, seconds: float) -> None:
        """Sleep up to `seconds`, returning as soon as shutdown is requested."""
        if self._wakeup_recv is None:
            # Not installed, so nothing can wake the wait early anyway.
            time.sleep(seconds)
            return
        deadline = time.monotonic() + seconds
        # One pass per delivered signal, not a poll: `select` blocks until
        # the deadline unless some signal writes a wakeup byte.
        while not self.requested:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            select.select([self._wakeup_recv], [], [], remaining)
            self._drain_wakeup_bytes()

    def _drain_wakeup_bytes(self) -> None:
        """Empty the wakeup socket so stale bytes don't cut a wait short."""
        assert self._wakeup_recv is not None
        # recv raises BlockingIOError (an OSError) once the socket is empty.
        with contextlib.suppress(OSError):
            while self._wakeup_recv.recv(4096):
                pass

    def _announce(self) -> None:
        if self._announced or self._signum is None:
            return
        self._announced = True
        if self._signum == signal.SIGINT:
            label = "ctrl-c"
        else:
            label = signal.Signals(self._signum).name
        termlog(
            f"{label} received. Finishing current scheduler iteration before exiting."
        )


@dataclass
class SchedulerOptions:
    """How a scheduler drives a sweep, independent of the search strategy.

    `executor` is the backend that schedules runs; the default is the W&B run
    queue.
    """

    poll_interval_s: float = 5.0
    batch_size: int = 1
    executor: Executor | None = None


class Scheduler(ABC):
    """Drive an `Optimizer` against a sweep, keeping `batch_size` in flight.

    Poll runs, tell the optimizer their results, and enqueue its suggestions.
    Subclasses implement the hooks below to choose where in-flight state lives
    and how runs are observed.
    See `InMemoryScheduler` for the default implementation.
    """

    def __init__(
        self,
        optimizer: Optimizer,
        sweep: Sweep,
        options: SchedulerOptions | None = None,
    ):
        options = options or SchedulerOptions()
        self._optimizer = optimizer
        self._sweep = sweep
        self._poll_interval_s = options.poll_interval_s
        self._batch_size = options.batch_size
        self._executor = options.executor or WBAgentExecutor(sweep)
        self._shutdown = _ShutdownMonitor()
        # The state read at the top of the current iteration; one read
        # serves everything in it.
        self._last_sweep_state: SweepState | None = None
        self._slowdown_s = 0.0
        self._consecutive_errors = 0

    @abstractmethod
    def in_flight_runs(self) -> Mapping[str, Any]:
        """The live, mutable {wandb_run_id: optimizer_run_id} in-flight map."""
        ...

    @abstractmethod
    def pop_in_flight_run(self, wandb_run_id: str) -> Any:
        """Remove a run from the in-flight set."""
        ...

    @abstractmethod
    def push_in_flight_run(self, wandb_run_id: str, optimizer_run_id: Any) -> None:
        """Add a run to the in-flight set.

        Raises:
            ValueError: If `wandb_run_id` is already in flight.
        """
        ...

    @abstractmethod
    def fetch_existing_finished_runs(self) -> Iterable[RunWithMetrics]:
        """Terminal runs already in the sweep, with their summary metrics."""
        ...

    @abstractmethod
    def fetch_existing_unfinished_runs(self) -> Iterable[Run]:
        """In-flight runs already in the sweep, without metrics, to adopt."""
        ...

    @abstractmethod
    def fetch_active_runs(self) -> Iterable[RunWithMetrics]:
        """The tracked in-flight runs, with fresh state/metrics and history."""
        ...

    @abstractmethod
    def sweep_state(self) -> SweepState:
        """The sweep's current state; the loop runs while RUNNING/PENDING."""
        ...

    def unreadable_run_ids(self) -> frozenset[str]:
        """W&B run ids the last `fetch_active_runs` saw but could not build.

        Such a run still exists on the server, so it must not be reaped as
        deleted. Override this alongside `fetch_active_runs` when that hook
        skips runs; the default reports none.
        """
        return frozenset()

    @abstractmethod
    def stop_run(self, wandb_run_id: str) -> bool:
        """Request that a run stop early; True if the stop was accepted."""
        ...

    def loop(self) -> None:
        """Warm-start, then poll and schedule runs until the sweep ends.

        Warm-starting runs first, so runs already in the sweep (e.g. from a
        previous scheduler instance) count toward the in-flight cap before any
        new ones are enqueued.

        `ShutdownSignal` (SIGTERM/SIGHUP/SIGQUIT) and `KeyboardInterrupt`
        (ctrl-c) let the current loop iteration finish before exiting.

        Intermittent W&B API failures don't end the sweep: the loop keeps
        polling, just further apart, until they clear or
        `_MAX_CONSECUTIVE_ERRORS` polls have failed in a row. Failures that
        won't resolve on their own end the loop immediately. See
        `failure_policy.classify`.

        Raises:
            Exception: The failure that ended the loop, when a W&B API call
                failed permanently or kept failing poll after poll.
        """
        self._reset_poll_slowdown()
        self._shutdown.install()  # also resets any earlier request
        try:
            # Not retried: `_warm_start` is not idempotent, so a second
            # attempt would double-count runs it already ingested.
            self._warm_start()

            while not self._shutdown.requested:
                try:
                    # Read inside the try so a failure here is handled too.
                    if self._refresh_sweep_state() not in _ACTIVE_SWEEP_STATES:
                        break
                    if self._loop_iteration() is _LoopControl.TERMINATE:
                        break
                    self._reset_poll_slowdown()
                except (KeyboardInterrupt, ShutdownSignal) as e:
                    signum = (
                        signal.SIGINT if isinstance(e, KeyboardInterrupt) else e.signum
                    )
                    self._shutdown.request(signum)
                    break
                except Exception as e:
                    self._handle_loop_error(e)  # re-raises unless survivable
                self._shutdown.wait(self._effective_poll_interval_s)
        finally:
            self._shutdown.restore()

        # Report the cached state: another query here could fail from a point
        # past the handling above.
        state = self._last_sweep_state
        if state is None:
            termlog(f"Sweep {self._sweep.name} has exited")
        else:
            termlog(f"Sweep {self._sweep.name} has exited with state {state}")

    def _refresh_sweep_state(self) -> SweepState:
        """Read the sweep's state and cache it for the current iteration."""
        self._last_sweep_state = self.sweep_state()
        return self._last_sweep_state

    @property
    def _effective_poll_interval_s(self) -> float:
        """How long to wait before the next poll, including any slowdown."""
        return self._poll_interval_s + self._slowdown_s

    def _reset_poll_slowdown(self) -> None:
        """Return to the normal poll rate after a clean iteration."""
        self._slowdown_s = 0.0
        self._consecutive_errors = 0

    def _handle_loop_error(self, exc: Exception) -> None:
        """Slow the poll rate down for a survivable `exc`, or re-raise it.

        `exc` is not retried here -- wandb-core already retried the call that
        raised it. The next poll will reach the same API anyway; slowing the
        loop down just spaces those polls out while W&B is unhealthy.

        Args:
            exc: The exception raised by the current loop iteration.

        Raises:
            Exception: `exc` itself, when it will not resolve on its own or too
                many polls have failed in a row.
        """
        disposition = classify(exc)
        if disposition is Disposition.NOT_FOUND:
            termerror(
                f"Sweep {self._sweep.name} or one of its runs no longer exists: {exc}"
            )
            raise exc
        if disposition is Disposition.FATAL:
            termerror(f"Error in scheduler loop for sweep {self._sweep.name}: {exc}")
            raise exc

        # Being throttled is the server working as intended, so it slows the
        # poll down indefinitely rather than counting toward giving up.
        if disposition is not Disposition.RATE_LIMITED:
            self._consecutive_errors += 1
            if self._consecutive_errors > _MAX_CONSECUTIVE_ERRORS:
                termerror(
                    f"Giving up on sweep {self._sweep.name} after "
                    f"{self._consecutive_errors} consecutive failed polls: {exc}"
                )
                raise exc

        self._slow_polling()
        if disposition is Disposition.RATE_LIMITED:
            termwarn(
                f"W&B is rate limiting the scheduler for sweep "
                f"{self._sweep.name}; polling every "
                f"{self._effective_poll_interval_s:.0f}s"
            )
        else:
            termwarn(
                f"Error polling sweep {self._sweep.name}; polling every "
                f"{self._effective_poll_interval_s:.0f}s until it clears: {exc}"
            )

    def _slow_polling(self) -> None:
        """Double the slowdown, from `_INITIAL_SLOWDOWN_S` up to the cap."""
        self._slowdown_s = min(
            max(self._slowdown_s * 2, _INITIAL_SLOWDOWN_S),
            _MAX_SLOWDOWN_S,
        )

    def _loop_iteration(self) -> _LoopControl:
        """Run one scheduler iteration."""
        # must reload the state just before calling this.
        if self._last_sweep_state == SweepState.PAUSED:
            return _LoopControl.CONTINUE
        active = self._poll_active_runs()
        self._prune_active_runs(active)
        if self._optimizer.should_terminate_sweep():
            termlog(
                f"Sweep {self._sweep.name} should be terminated;exiting scheduler loop."
            )
            self._sweep.finish()
            return _LoopControl.TERMINATE
        # Reconcile against the executor's backend: drop runs whose job died
        # before reporting to W&B (otherwise they'd pin capacity).
        self._reap_dead_runs()
        return self._schedule_suggestions()

    def _warm_start(self) -> None:
        # Warm-start must never block the loop from proposing new runs; errors
        # ingesting an existing run are skipped with a warning.
        for run in self.fetch_existing_finished_runs():
            try:
                self._optimizer.tell_existing_finished_run(run)
            except Exception as e:
                termwarn(
                    f"Skipping finished run {run.wandb_run_id} while warm-starting "
                    f"sweep {self._sweep.name}: {e}"
                )
        for active_run in self.fetch_existing_unfinished_runs():
            # Adopt it so the loop keeps driving it and it counts toward the
            # in-flight cap, instead of being re-proposed.
            try:
                optimizer_run_id = self._optimizer.tell_existing_active_run(active_run)
                if optimizer_run_id is not None:
                    self.push_in_flight_run(active_run.wandb_run_id, optimizer_run_id)
            except Exception as e:
                termwarn(
                    f"Skipping unfinished run {active_run.wandb_run_id} while "
                    f"warm-starting sweep {self._sweep.name}: {e}"
                )

    def _poll_active_runs(self) -> Iterable[RunWithMetrics]:
        in_flight = self.in_flight_runs()
        active = self.fetch_active_runs()
        for data in active:
            wandb_run_id = data.wandb_run_id
            if wandb_run_id not in in_flight:
                # A run we didn't enqueue (e.g. pre-existing); ignore it.
                continue
            optimizer_run_id = in_flight[wandb_run_id]

            if (
                self._optimizer.metric_value(data.summary_metrics) is None
                and data.state == RunState.FINISHED
            ):
                termwarn(
                    f"Run {wandb_run_id} in sweep {self._sweep.name} "
                    f"has no metric value"
                )
                data.state = RunState.FAILED

            try:
                self._optimizer.tell_run(optimizer_run_id, data)
            except Exception as e:
                termerror(
                    f"Error telling run {wandb_run_id} in sweep {self._sweep.name}: {e}"
                )
                raise

            if data.state.value in _TERMINAL_STATES:
                self.pop_in_flight_run(wandb_run_id)
        self._reap_deleted_runs(active)
        return active

    def _prune_active_runs(self, active: Iterable[RunWithMetrics]) -> None:
        # Ask the optimizer whether to stop any run still in flight after this
        # poll's results were told to it. Separate from `_poll_active_runs` so
        # every run's outcome is recorded before any pruning decision is made.
        in_flight = self.in_flight_runs()
        candidates: list[tuple[str, Any, RunWithMetrics]] = []
        for data in active:
            wandb_run_id = data.wandb_run_id
            if wandb_run_id not in in_flight or data.state not in [
                RunState.RUNNING,
                RunState.PENDING,
            ]:
                continue
            candidates.append((wandb_run_id, in_flight[wandb_run_id], data))
        if not candidates:
            return

        optimizer_run_ids = [optimizer_run_id for _, optimizer_run_id, _ in candidates]
        runs = [data for _, _, data in candidates]
        wandb_run_id_by_optimizer_run_id = {
            optimizer_run_id: wandb_run_id
            for wandb_run_id, optimizer_run_id, _ in candidates
        }
        for optimizer_run_id in self._optimizer.prune_runs(optimizer_run_ids, runs):
            if optimizer_run_id not in wandb_run_id_by_optimizer_run_id:
                continue
            wandb_run_id = wandb_run_id_by_optimizer_run_id[optimizer_run_id]
            termlog(
                f"Pruning run {wandb_run_id} (optimizer run {optimizer_run_id}) "
                f"in sweep {self._sweep.name}"
            )
            if self.stop_run(wandb_run_id):
                self.pop_in_flight_run(wandb_run_id)

    def _reap_deleted_runs(self, active: Iterable[Run]) -> None:
        # A run that was seen but didn't build is still on the server, so it
        # counts as present and is retried next poll rather than failed.
        present = set(run.wandb_run_id for run in active) | self.unreadable_run_ids()
        runs = set(self.in_flight_runs().keys())
        for wandb_run_id in runs - present:
            self._optimizer.tell_run(
                self.in_flight_runs()[wandb_run_id],
                RunWithMetrics(
                    # The run is gone from W&B, so there is no config to
                    # read back; the outcome (failed) is all the optimizer
                    # needs.
                    config=RunConfig({}),
                    state=RunState.FAILED,
                    wandb_run_id=wandb_run_id,
                    summary_metrics={},
                    history_metrics=[],
                ),
            )
            self.pop_in_flight_run(wandb_run_id)

    def _reap_dead_runs(self) -> None:
        """Fail and drain in-flight runs whose backend job is no longer alive.

        A direct executor (e.g. SLURM/Volcano) may schedule a job that never
        reaches `wandb.init` (rejected, preempted, crashed at startup), leaving
        its W&B run stuck PENDING and pinned in-flight forever.
        """
        in_flight = self.in_flight_runs()
        if not in_flight:
            return
        for run_id in self._executor.reap(set(in_flight)):
            optimizer_run_id = in_flight.get(run_id)
            if optimizer_run_id is None:
                continue
            termwarn(
                f"Run {run_id} in sweep {self._sweep.name} is no longer alive at "
                f"the executor but never reached a terminal W&B state; marking it "
                f"failed."
            )
            data = RunWithMetrics(
                # The run never reported to W&B, so there is no config to read
                # back; the outcome (failed) is all the optimizer needs here.
                config=RunConfig({}),
                state=RunState.FAILED,
                wandb_run_id=run_id,
                summary_metrics={},
                history_metrics=[],
            )
            try:
                self._optimizer.tell_run(optimizer_run_id, data)
            except Exception as e:
                termerror(
                    f"Error telling reaped run {run_id} in sweep "
                    f"{self._sweep.name}: {e}"
                )
            self.pop_in_flight_run(run_id)

    def _schedule_suggestions(self) -> _LoopControl:
        """Top the sweep back up to `batch_size` runs in flight."""
        # Keep at most `batch_size` runs in flight. `in_flight_runs` is
        # populated on enqueue/adoption and drained as runs go terminal, so its
        # size is the in-flight count.
        in_flight = self.in_flight_runs()
        n_to_enqueue = self._batch_size - len(in_flight)
        if n_to_enqueue <= 0:
            return _LoopControl.CONTINUE
        suggestions = self._next_suggestions(n_to_enqueue)
        if suggestions is None:
            # search was interrupted
            return _LoopControl.CONTINUE
        if len(suggestions) == 0:
            # search space is exhausted
            return _LoopControl.TERMINATE
        for suggestion in suggestions:
            wandb_run_id = self._executor.schedule(suggestion)
            self.push_in_flight_run(wandb_run_id, suggestion.run_id)
            termlog(
                f"Scheduled run {wandb_run_id} (optimizer run {suggestion.run_id}) "
                f"in sweep {self._sweep.name} with config "
                f"{suggestion.config.flat_dict()}"
            )
        return _LoopControl.CONTINUE

    def _next_suggestions(self, n: int) -> Sequence[RunSuggestion] | None:
        """Ask the optimizer for up to `n` runs, polling sweep state.

        An optimizer that proposes nothing has exhausted its search space (grid
        search, for one, stops proposing once every point has been handed out),
        so there is nothing left to schedule and the sweep is finished here.

        Returns:
            The runs to enqueue; an empty sequence once the search space is
            exhausted and the sweep has been finished; or None when the sweep
            leaves RUNNING/PENDING/PAUSED (or a shutdown is requested) before
            the optimizer responds, so the loop can exit without enqueueing
            new runs.
        """
        suggestions: list[RunSuggestion] | None = None
        done = threading.Event()

        def fetch() -> None:
            nonlocal suggestions
            suggestions = list(self._optimizer.ask_n_runs(n))
            done.set()

        thread = threading.Thread(target=fetch, daemon=True)
        thread.start()
        # Waiting on the optimizer can outlast the state read at the top of the
        # iteration, so these reads are fresh -- at the same slowed-down rate,
        # so a throttled scheduler queries less often here too.
        while not done.wait(timeout=self._effective_poll_interval_s):
            if self._shutdown.requested:
                return None
            if self._refresh_sweep_state() not in _ACTIVE_SWEEP_STATES:
                return None
        if not suggestions:
            termlog(
                f"Optimizer for sweep {self._sweep.name} has no runs left to "
                f"suggest; the search space is exhausted. Finishing sweep."
            )
            self._sweep.finish()
            return []
        return suggestions

    def _build_runs(
        self, runs: Iterable[Any], builder: Callable[[Any], _RunT]
    ) -> Iterator[_RunT]:
        # Lazily yield built runs as the paginated query advances, so warm-start
        # can process them a page at a time rather than holding every run in
        # memory.
        for run in runs:
            # A single unreadable run must not abort warm-starting the rest.
            try:
                built = builder(run)
            except Exception as e:
                termwarn(
                    f"Skipping run {run.id} while warm-starting sweep "
                    f"{self._sweep.name}: {e}"
                )
                continue
            yield built
