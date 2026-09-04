"""Unit tests of SchedulerTaskExchange, in pure Python.

Both `ServiceConnection` and `Optimizer` are mocked: no wandb-core process
or backend is involved. For the few tests that exercise the real IPC path
end-to-end, see tests/system_tests/test_sweep/test_sweep_scheduler_e2e.py.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from unittest.mock import Mock

import pytest
from wandb.proto import wandb_sweep_scheduler_pb2 as sspb
from wandb.sdk.lib.service.service_connection import ServiceConnection
from wandb.sdk.mailbox import HandleAbandonedError, MailboxHandle
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.ipc import (
    SchedulerServiceExitedError,
    SchedulerTaskExchange,
    describe_done,
    forget_discards,
)
from wandb.sdk.sweeps.scheduler.optimizer import Optimizer, RunConfig, RunSuggestion


def make_optimizer() -> Mock:
    """A Mock(spec=Optimizer) with the production no-op hook defaults.

    Tests configure `return_value`/`side_effect` on only the hooks they
    exercise; hook calls are visible in order via `optimizer.mock_calls`.
    """
    optimizer = Mock(spec=Optimizer)
    optimizer.ask_n_runs.return_value = None
    optimizer.tell_existing_active_run.return_value = None
    optimizer.prune_runs.return_value = []
    optimizer.should_terminate_sweep.return_value = False
    return optimizer


def make_service(
    tasks: list[sspb.SweepSchedulerServerNextTaskResponse | None],
) -> Mock:
    """A Mock(spec=ServiceConnection) that scripts next-task responses.

    A None entry in the script simulates wandb-core dying: the handle
    for that poll is abandoned.
    """
    tasks = list(tasks)
    service = Mock(spec=ServiceConnection)

    async def next_task(session_id, result):
        handle = Mock(spec=MailboxHandle)
        response = tasks.pop(0)
        if response is None:
            handle.wait_async.side_effect = HandleAbandonedError
        else:
            handle.wait_async.return_value = response
        return handle

    service.sweep_scheduler_next_task.side_effect = next_task
    return service


def sent_results(
    service: Mock,
) -> list[sspb.SweepSchedulerClientTaskResult | None]:
    """The `result` argument of each `sweep_scheduler_next_task` call."""
    return [c.args[1] for c in service.sweep_scheduler_next_task.call_args_list]


def warm_task(
    seq: int,
    *,
    finished: Sequence[str] = (),
    active: Sequence[str] = (),
    has_more: bool = False,
) -> sspb.SweepSchedulerServerNextTaskResponse:
    task = sspb.SweepSchedulerServerWarmStartTask(has_more=has_more)
    for name in finished:
        task.finished_runs.append(
            sspb.SweepSchedulerServerRunData(
                wandb_run_id=name,
                state=sspb.SWEEP_RUN_STATE_FINISHED,
                config_json='{"param1": 1}',
                summary_json='{"loss": 0.5}',
            )
        )
    for name in active:
        task.active_runs.append(
            sspb.SweepSchedulerServerRunData(
                wandb_run_id=name,
                state=sspb.SWEEP_RUN_STATE_RUNNING,
                config_json='{"param1": 2}',
            )
        )
    return sspb.SweepSchedulerServerNextTaskResponse(task_seq=seq, warm_start=task)


def generation_task(
    seq: int,
    *,
    updates: dict[str, int] | None = None,
    ask_up_to: int = 0,
    prune_candidates: Sequence[str] = (),
    discarded: Sequence[str] = (),
) -> sspb.SweepSchedulerServerNextTaskResponse:
    task = sspb.SweepSchedulerServerGenerationTask(
        ask_up_to=ask_up_to,
        prune_candidates=prune_candidates,
        discarded_optimizer_run_ids=discarded,
    )
    for run_id, state in (updates or {}).items():
        task.updates.append(
            sspb.SweepSchedulerServerRunUpdate(
                run=sspb.SweepSchedulerServerRunData(
                    wandb_run_id=f"wandb-{run_id}",
                    optimizer_run_id=run_id,
                    state=state,
                    config_json='{"param1": 1}',
                    summary_json='{"loss": 1.0}',
                    history_json='[{"loss": 1.0}]',
                )
            )
        )
    return sspb.SweepSchedulerServerNextTaskResponse(task_seq=seq, generation=task)


def done_task(
    seq: int,
    reason=sspb.SweepSchedulerServerDoneTask.REASON_EXHAUSTED,
    discarded: Sequence[str] = (),
) -> sspb.SweepSchedulerServerNextTaskResponse:
    return sspb.SweepSchedulerServerNextTaskResponse(
        task_seq=seq,
        done=sspb.SweepSchedulerServerDoneTask(
            reason=reason,
            discarded_optimizer_run_ids=discarded,
        ),
    )


def run_exchange(
    service: Mock,
    optimizer: Mock,
) -> sspb.SweepSchedulerServerDoneTask:
    exchange = SchedulerTaskExchange(service, "scheduler-0", optimizer)  # type: ignore[arg-type]
    return asyncio.run(exchange.run())


def test_warm_start_adoptions_and_skips():
    optimizer = make_optimizer()

    def tell_existing_finished_run(data):
        if data.wandb_run_id == "poison":
            raise RuntimeError("cannot ingest poison")

    optimizer.tell_existing_finished_run.side_effect = tell_existing_finished_run
    optimizer.tell_existing_active_run.side_effect = lambda data: (
        f"adopted-{data.wandb_run_id}"
    )
    service = make_service(
        [
            warm_task(1, finished=["good", "poison"], active=["running"]),
            done_task(2),
        ]
    )

    run_exchange(service, optimizer)

    result = sent_results(service)[1]
    assert result.task_seq == 1
    warm = result.warm_start
    assert dict(warm.adoptions) == {"running": "adopted-running"}
    assert [s.wandb_run_id for s in warm.skipped] == ["poison"]
    # The good run was ingested despite the poison one.
    told_finished = [
        c.args[0].wandb_run_id
        for c in optimizer.tell_existing_finished_run.call_args_list
    ]
    assert "good" in told_finished


def test_generation_orders_tell_prune_terminate_ask():
    optimizer = make_optimizer()
    optimizer.ask_n_runs.return_value = [
        RunSuggestion(config=RunConfig.from_values({"param1": 3}), run_id="s1")
    ]
    service = make_service(
        [
            generation_task(
                1,
                updates={"r1": sspb.SWEEP_RUN_STATE_RUNNING},
                ask_up_to=2,
                prune_candidates=["r1"],
            ),
            done_task(2),
        ]
    )

    run_exchange(service, optimizer)

    kinds = [c[0] for c in optimizer.mock_calls]
    assert kinds == [
        "tell_run",
        "prune_runs",
        "should_terminate_sweep",
        "ask_n_runs",
    ]

    generation = sent_results(service)[1].generation
    assert (
        generation.ask_outcome
        == sspb.SweepSchedulerClientGenerationResult.ASK_OUTCOME_SUGGESTED
    )
    assert generation.suggestions[0].optimizer_run_id == "s1"
    assert json.loads(generation.suggestions[0].config_json) == {"param1": 3}


def test_ask_outcomes_encode_exhausted_and_declined():
    optimizer = make_optimizer()
    optimizer.ask_n_runs.side_effect = [None, []]
    service = make_service(
        [
            generation_task(1, ask_up_to=1),
            generation_task(2, ask_up_to=1),
            done_task(3),
        ]
    )

    run_exchange(service, optimizer)

    results = sent_results(service)
    assert (
        results[1].generation.ask_outcome
        == sspb.SweepSchedulerClientGenerationResult.ASK_OUTCOME_DECLINED
    )
    assert (
        results[2].generation.ask_outcome
        == sspb.SweepSchedulerClientGenerationResult.ASK_OUTCOME_EXHAUSTED
    )


def test_optimizer_exception_becomes_task_error():
    optimizer = make_optimizer()
    optimizer.ask_n_runs.side_effect = RuntimeError("ask exploded")
    service = make_service(
        [
            generation_task(1, ask_up_to=1),
            done_task(
                2, reason=sspb.SweepSchedulerServerDoneTask.REASON_OPTIMIZER_ERROR
            ),
        ]
    )

    done = run_exchange(service, optimizer)

    error = sent_results(service)[1].error
    assert "ask exploded" in error.message
    assert "RuntimeError" in error.traceback
    assert done.reason == sspb.SweepSchedulerServerDoneTask.REASON_OPTIMIZER_ERROR


def test_redelivered_task_answered_from_cache():
    optimizer = make_optimizer()
    service = make_service(
        [
            generation_task(1, updates={"r1": sspb.SWEEP_RUN_STATE_RUNNING}),
            # The same task again: the previous response was lost.
            generation_task(1, updates={"r1": sspb.SWEEP_RUN_STATE_RUNNING}),
            done_task(2),
        ]
    )

    run_exchange(service, optimizer)

    # The optimizer saw the update exactly once, and the retried poll
    # carried a byte-identical result.
    assert optimizer.tell_run.call_count == 1
    results = sent_results(service)
    assert results[1].SerializeToString() == results[2].SerializeToString()


def test_tell_error_reported_and_prune_candidates_filtered():
    optimizer = make_optimizer()

    def tell_run(run_id, data):
        if run_id == "poison":
            raise RuntimeError(f"cannot ingest {run_id}")

    optimizer.tell_run.side_effect = tell_run
    service = make_service(
        [
            generation_task(
                1,
                updates={
                    "poison": sspb.SWEEP_RUN_STATE_RUNNING,
                    "good": sspb.SWEEP_RUN_STATE_RUNNING,
                },
                prune_candidates=["poison", "good"],
            ),
            done_task(2),
        ]
    )

    run_exchange(service, optimizer)

    generation = sent_results(service)[1].generation
    assert [e.optimizer_run_id for e in generation.tell_errors] == ["poison"]
    # Only the successfully told run was offered for pruning.
    assert optimizer.prune_runs.call_args.args[0] == ["good"]


def test_discarded_suggestions_are_forgotten():
    optimizer = make_optimizer()
    service = make_service(
        [
            generation_task(1, discarded=["lost-1", "lost-2"]),
            done_task(2),
        ]
    )

    run_exchange(service, optimizer)

    forgets = [c.args[0] for c in optimizer.forget_run.call_args_list]
    assert forgets == ["lost-1", "lost-2"]


def test_done_discards_are_forgotten():
    optimizer = make_optimizer()
    done = sspb.SweepSchedulerServerDoneTask(
        reason=sspb.SweepSchedulerServerDoneTask.REASON_SHUTDOWN,
        discarded_optimizer_run_ids=["final"],
    )

    forget_discards(optimizer, done)

    optimizer.forget_run.assert_called_once_with("final")


def test_abandoned_handle_raises_service_exited():
    optimizer = make_optimizer()
    service = make_service([None])

    with pytest.raises(SchedulerServiceExitedError):
        run_exchange(service, optimizer)

    # The optimizer was never touched.
    assert optimizer.mock_calls == []


def test_unknown_run_state_maps_to_unknown():
    optimizer = make_optimizer()
    told_states: list[RunState] = []
    optimizer.tell_run.side_effect = lambda run_id, data: told_states.append(data.state)
    service = make_service(
        [
            generation_task(
                1,
                updates={
                    "r1": sspb.SWEEP_RUN_STATE_UNKNOWN,
                    "r2": sspb.SWEEP_RUN_STATE_FINISHED,
                },
            ),
            done_task(2),
        ]
    )

    run_exchange(service, optimizer)

    assert set(told_states) == {RunState.UNKNOWN, RunState.FINISHED}


def test_describe_done_marks_errors():
    _, fatal = describe_done(
        sspb.SweepSchedulerServerDoneTask(
            reason=sspb.SweepSchedulerServerDoneTask.REASON_FATAL_ERROR
        )
    )
    message, clean = describe_done(
        sspb.SweepSchedulerServerDoneTask(
            reason=sspb.SweepSchedulerServerDoneTask.REASON_EXHAUSTED,
            message="42 runs",
        )
    )

    assert fatal
    assert not clean
    assert "exhausted" in message
    assert "42 runs" in message
