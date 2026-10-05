"""Exchanges sweep-scheduler tasks between wandb-core and an Optimizer.

The scheduling loop lives in wandb-core; this module is the Python side:
a stateless task exchange that long-polls for the next task, runs the
optimizer's ask/tell hooks, and reports each task's result on the
following poll.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from collections.abc import Iterable

from wandb.proto import wandb_sweep_scheduler_pb2 as sspb
from wandb.sdk.lib.service.service_connection import ServiceConnection
from wandb.sdk.mailbox import HandleAbandonedError, MailboxClosedError
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.optimizer import (
    Optimizer,
    Run,
    RunConfig,
    RunWithMetrics,
    is_terminal_state,
)


class SchedulerServiceExitedError(Exception):
    """wandb-core went away while the scheduler was running."""


_RUN_STATE_FROM_PROTO: dict[int, RunState] = {
    sspb.SWEEP_RUN_STATE_RUNNING: RunState.RUNNING,
    sspb.SWEEP_RUN_STATE_PENDING: RunState.PENDING,
    sspb.SWEEP_RUN_STATE_PREEMPTING: RunState.PREEMPTING,
    sspb.SWEEP_RUN_STATE_PREEMPTED: RunState.PREEMPTED,
    sspb.SWEEP_RUN_STATE_FINISHED: RunState.FINISHED,
    sspb.SWEEP_RUN_STATE_FAILED: RunState.FAILED,
    sspb.SWEEP_RUN_STATE_CRASHED: RunState.CRASHED,
    sspb.SWEEP_RUN_STATE_KILLED: RunState.KILLED,
}


def _run_state_from_proto(state: int) -> RunState:
    """Map a protocol run state onto RunState, defaulting to UNKNOWN.

    UNKNOWN is classified alive, which is the safe reading of a state
    this client version does not recognize.
    """
    return _RUN_STATE_FROM_PROTO.get(state, RunState.UNKNOWN)


def _config_from_json(config_json: str) -> RunConfig:
    return RunConfig.from_values(json.loads(config_json or "{}"))


def _to_run(data: sspb.SweepSchedulerServerRunData) -> Run:
    return Run(
        config=_config_from_json(data.config_json),
        state=_run_state_from_proto(data.state),
        wandb_run_id=data.wandb_run_id,
    )


def _to_run_with_metrics(
    data: sspb.SweepSchedulerServerRunData,
) -> RunWithMetrics:
    return RunWithMetrics(
        config=_config_from_json(data.config_json),
        state=_run_state_from_proto(data.state),
        wandb_run_id=data.wandb_run_id,
        summary_metrics=json.loads(data.summary_json or "{}"),
        history_metrics=json.loads(data.history_json or "[]"),
    )


class SchedulerTaskExchange:
    """Long-polls wandb-core for optimizer tasks and reports results."""

    def __init__(
        self,
        service: ServiceConnection,
        scheduler_id: str,
        optimizer: Optimizer,
        handler: logging.Handler,
    ) -> None:
        self._service = service
        self._id = scheduler_id
        self._optimizer = optimizer

        # Unresolved suggestions (no update or discard yet), by config JSON.
        self._await_enqueue: dict[str, str] = {}

        self._is_warm_starting = False

        # Each run's last reported state, so only transitions are logged.
        self._seen_states: dict[str, RunState] = {}

        # Per-session logger so concurrent exchanges do not share handlers.
        self._logger = logging.getLogger(f"wandb.sweep_scheduler.{scheduler_id}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._logger.addHandler(handler)

    async def run(self) -> sspb.SweepSchedulerServerDoneTask:
        """Exchange tasks until the scheduler is done.

        Returns:
            The scheduler's Done task, describing why it stopped.

        Raises:
            SchedulerServiceExitedError: If wandb-core exited. The sweep's
                state is stored on the backend, so rerunning the scheduler
                resumes it.
        """
        result: sspb.SweepSchedulerClientTaskResult | None = None
        while True:
            handle = await self._service.sweep_scheduler_next_task(self._id, result)
            try:
                response = await handle.wait_async(timeout=None)
            except (HandleAbandonedError, MailboxClosedError):
                raise SchedulerServiceExitedError(
                    "wandb-core exited. The sweep's state is stored on "
                    "the backend; rerun the scheduler to resume it."
                ) from None
            except asyncio.CancelledError:
                # Cancel rather than abandon so the server can release
                # the request.
                handle.cancel()
                raise

            if response.WhichOneof("task") == "done":
                return response.done

            # Optimizer calls can block for minutes; run them off the
            # event loop so the mailbox stays responsive.
            result = await asyncio.to_thread(self._execute, response)
            result.task_seq = response.task_seq

    def _log_run(self, run: Run) -> None:
        self._logger.info(
            f"Run {run.wandb_run_id} loaded as {run.state.name.lower()}."
        )

    def _drop_enqueued(
        self,
        discarded: Iterable[str],
        updates: Iterable[sspb.SweepSchedulerServerRunUpdate],
    ) -> None:
        """Report the fate of suggestions sent with earlier results.

        A discarded suggestion was never scheduled. An enqueued one is named
        by the W&B run id it first appears under in an update, and waits
        until then.
        """
        if not self._await_enqueue:
            return

        dropped = set(discarded)
        wandb_run_ids = {
            update.run.optimizer_run_id: update.run.wandb_run_id for update in updates
        }
        for run_id, config_json in list(self._await_enqueue.items()):
            if run_id in dropped:
                self._logger.warning(f"Run with config {config_json} was deleted.")
            elif run_id in wandb_run_ids:
                self._logger.info(
                    f"Enqueued run {wandb_run_ids[run_id]} with config {config_json}."
                )
            else:
                continue
            del self._await_enqueue[run_id]

    def _track_state_changes(
        self,
        updates: Iterable[sspb.SweepSchedulerServerRunUpdate],
    ) -> None:
        """Report run-state transitions as the backend sees them.

        A run's terminal update is its last, so the run is forgotten after it.
        """
        for update in updates:
            run_id = update.run.optimizer_run_id
            state = _run_state_from_proto(update.run.state)
            if is_terminal_state(state):
                self._seen_states.pop(run_id, None)
            elif self._seen_states.get(run_id) == state:
                continue
            else:
                self._seen_states[run_id] = state
            self._logger.info(
                f"Run {update.run.wandb_run_id} is {state.name.lower()}."
            )

    def _execute(
        self,
        response: sspb.SweepSchedulerServerNextTaskResponse,
    ) -> sspb.SweepSchedulerClientTaskResult:
        """Run the optimizer hooks for one task and build its result.

        Only per-run tells are fault-tolerant; an exception anywhere else
        becomes a task error, which stops the scheduler without finishing
        the sweep.
        """
        try:
            if response.WhichOneof("task") == "warm_start":
                return sspb.SweepSchedulerClientTaskResult(
                    warm_start=self._execute_warm_start(response.warm_start)
                )
            return sspb.SweepSchedulerClientTaskResult(
                generation=self._execute_generation(response.generation)
            )
        except Exception as e:
            return sspb.SweepSchedulerClientTaskResult(
                error=sspb.SweepSchedulerClientTaskError(
                    message=str(e),
                    traceback=traceback.format_exc(),
                )
            )

    def _execute_warm_start(
        self,
        task: sspb.SweepSchedulerServerWarmStartTask,
    ) -> sspb.SweepSchedulerClientWarmStartResult:
        result = sspb.SweepSchedulerClientWarmStartResult()

        if not self._is_warm_starting:
            self._is_warm_starting = True
            self._logger.info("Loading run state from the backend.")
        page_size = len(task.finished_runs) + len(task.active_runs)
        self._logger.info(f"Processing {page_size} runs in this page.")

        for data in task.finished_runs:
            run = _to_run_with_metrics(data)
            self._log_run(run)
            try:
                self._optimizer.tell_existing_finished_run(run)
            except Exception as e:
                result.skipped.append(
                    sspb.SweepSchedulerClientSkippedRun(
                        wandb_run_id=data.wandb_run_id, error=str(e)
                    )
                )
                self._logger.warning(
                    f"Optimizer rejected run {data.wandb_run_id}: {e}"
                )

        for data in task.active_runs:
            run = _to_run(data)
            self._log_run(run)
            try:
                run_id = self._optimizer.tell_existing_active_run(run)
            except Exception as e:
                result.skipped.append(
                    sspb.SweepSchedulerClientSkippedRun(
                        wandb_run_id=data.wandb_run_id, error=str(e)
                    )
                )
                self._logger.warning(
                    f"Optimizer rejected run {data.wandb_run_id}: {e}"
                )
                continue
            if run_id is not None:
                result.adoptions[data.wandb_run_id] = str(run_id)

        if not task.has_more:
            self._is_warm_starting = False
            self._logger.info("Finished loading run state.")

        return result

    def _execute_generation(
        self,
        task: sspb.SweepSchedulerServerGenerationTask,
    ) -> sspb.SweepSchedulerClientGenerationResult:
        result = sspb.SweepSchedulerClientGenerationResult()

        self._drop_enqueued(task.discarded_optimizer_run_ids, task.updates)
        self._track_state_changes(task.updates)

        for run_id in task.discarded_optimizer_run_ids:
            self._optimizer.forget_run(run_id)

        told: dict[str, RunWithMetrics] = {}
        for update in task.updates:
            run_id = update.run.optimizer_run_id
            data = _to_run_with_metrics(update.run)
            try:
                self._optimizer.tell_run(run_id, data)
            except Exception as e:
                result.tell_errors.append(
                    sspb.SweepSchedulerClientTellError(
                        optimizer_run_id=run_id, message=str(e)
                    )
                )
                continue
            told[run_id] = data

        # Only runs whose tell succeeded are offered for pruning: the
        # optimizer cannot judge a run it failed to ingest.
        candidates = [run_id for run_id in task.prune_candidates if run_id in told]
        if candidates:
            result.prune.extend(
                self._optimizer.prune_runs(
                    candidates, [told[run_id] for run_id in candidates]
                )
            )
            for run_id in result.prune:
                self._logger.info(
                    f"Requesting early stop of run {told[run_id].wandb_run_id}."
                )

        result.terminate = self._optimizer.should_terminate_sweep()

        if task.ask_up_to > 0 and not result.terminate:
            self._execute_ask(task.ask_up_to, result)

        return result

    def _execute_ask(
        self,
        ask_up_to: int,
        result: sspb.SweepSchedulerClientGenerationResult,
    ) -> None:
        engine = self._optimizer.engine
        self._logger.info(f"{engine} optimizer is generating {ask_up_to} new runs")
        started = time.perf_counter()
        suggestions = self._optimizer.ask_n_runs(ask_up_to)
        elapsed = time.perf_counter() - started
        generated = 0 if suggestions is None else len(suggestions)
        self._logger.info(
            f"{engine} optimizer generated {generated} runs in {elapsed:.2f}s"
        )

        if suggestions is None:
            result.ask_outcome = (
                sspb.SweepSchedulerClientGenerationResult.ASK_OUTCOME_DECLINED
            )
            return
        if not suggestions:
            result.ask_outcome = (
                sspb.SweepSchedulerClientGenerationResult.ASK_OUTCOME_EXHAUSTED
            )
            return

        result.ask_outcome = (
            sspb.SweepSchedulerClientGenerationResult.ASK_OUTCOME_SUGGESTED
        )
        await_enqueue: dict[str, str] = {}
        for suggestion in suggestions:
            run_id = str(suggestion.run_id)
            config_json = json.dumps(suggestion.config.flat_dict())
            result.suggestions.append(
                sspb.SweepSchedulerClientRunSuggestion(
                    optimizer_run_id=run_id,
                    config_json=config_json,
                )
            )
            await_enqueue[run_id] = config_json

        self._await_enqueue.update(await_enqueue)


def describe_done(done: sspb.SweepSchedulerServerDoneTask) -> tuple[str, bool]:
    """Return a user-facing message and whether the reason is an error.

    Args:
        done: The scheduler's terminal task.
    """
    reason = done.reason
    messages: dict[int, tuple[str, bool]] = {
        sspb.SweepSchedulerServerDoneTask.REASON_TERMINATED: (
            "the optimizer terminated the sweep",
            False,
        ),
        sspb.SweepSchedulerServerDoneTask.REASON_SWEEP_FINISHED: (
            "the sweep finished or was canceled",
            False,
        ),
        sspb.SweepSchedulerServerDoneTask.REASON_SWEEP_NOT_FOUND: (
            "the sweep was deleted",
            True,
        ),
        sspb.SweepSchedulerServerDoneTask.REASON_FATAL_ERROR: (
            "a fatal error stopped the scheduler",
            True,
        ),
        sspb.SweepSchedulerServerDoneTask.REASON_OPTIMIZER_ERROR: (
            "the optimizer failed; the sweep can be resumed",
            True,
        ),
        sspb.SweepSchedulerServerDoneTask.REASON_SHUTDOWN: (
            "the scheduler was stopped; the sweep can be resumed",
            False,
        ),
    }
    message, is_error = messages.get(reason, ("the scheduler stopped", False))

    if done.message:
        message = f"{message} ({done.message})"
    return message, is_error
