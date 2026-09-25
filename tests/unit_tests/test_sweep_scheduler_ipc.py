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
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_sweep_scheduler_pb2 as sspb
from wandb.sdk.lib.service import service_connection
from wandb.sdk.lib.service.service_client import ServiceClient
from wandb.sdk.lib.service.service_connection import ServiceConnection
from wandb.sdk.mailbox import HandleAbandonedError, MailboxClosedError, MailboxHandle
from wandb.sdk.sweeps.run_state import RunState
from wandb.sdk.sweeps.scheduler.ipc import (
    SchedulerServiceExitedError,
    SchedulerTaskExchange,
    describe_done,
)
from wandb.sdk.sweeps.scheduler.optimizer import Optimizer, RunConfig, RunSuggestion
from wandb.sdk.wandb_settings import Settings


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
    *,
    exit_error: type[BaseException] = HandleAbandonedError,
) -> Mock:
    """A Mock(spec=ServiceConnection) that scripts next-task responses.

    A None entry in the script simulates wandb-core dying: the handle
    for that poll raises `exit_error`.
    """
    tasks = list(tasks)
    service = Mock(spec=ServiceConnection)

    async def next_task(session_id, result):
        handle = Mock(spec=MailboxHandle)
        response = tasks.pop(0)
        if response is None:
            handle.wait_async.side_effect = exit_error
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
) -> sspb.SweepSchedulerServerNextTaskResponse:
    task = sspb.SweepSchedulerServerWarmStartTask()
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
    reason=sspb.SweepSchedulerServerDoneTask.REASON_SWEEP_FINISHED,
) -> sspb.SweepSchedulerServerNextTaskResponse:
    return sspb.SweepSchedulerServerNextTaskResponse(
        task_seq=seq,
        done=sspb.SweepSchedulerServerDoneTask(reason=reason),
    )


def run_exchange(
    service: Mock,
    optimizer: Mock,
) -> sspb.SweepSchedulerServerDoneTask:
    exchange = SchedulerTaskExchange(  # type: ignore[arg-type]
        service, "scheduler-0", optimizer
    )
    return asyncio.run(exchange.run())


def test_warm_start_adoptions_and_skips():
    optimizer = make_optimizer()

    def tell_existing_finished_run(data):
        if data.wandb_run_id == "poison":
            raise RuntimeError("cannot ingest poison")

    def tell_existing_active_run(data):
        if data.wandb_run_id == "poison-active":
            raise RuntimeError("cannot adopt poison")
        return f"adopted-{data.wandb_run_id}"

    optimizer.tell_existing_finished_run.side_effect = tell_existing_finished_run
    optimizer.tell_existing_active_run.side_effect = tell_existing_active_run
    service = make_service(
        [
            warm_task(
                1,
                finished=["good", "poison"],
                active=["running", "poison-active"],
            ),
            done_task(2),
        ]
    )

    run_exchange(service, optimizer)

    result = sent_results(service)[1]
    assert result.task_seq == 1
    warm = result.warm_start
    assert dict(warm.adoptions) == {"running": "adopted-running"}
    # A failed adopt is skipped like a failed tell, and never adopted.
    assert [s.wandb_run_id for s in warm.skipped] == ["poison", "poison-active"]
    # The good run was ingested despite the poison one.
    told_finished = [
        c.args[0].wandb_run_id
        for c in optimizer.tell_existing_finished_run.call_args_list
    ]
    assert "good" in told_finished


def test_generation_orders_tell_prune_terminate_ask():
    optimizer = make_optimizer()
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


_ASK = sspb.SweepSchedulerClientGenerationResult


@pytest.mark.parametrize(
    ("suggestions", "outcome", "encoded"),
    [
        (None, _ASK.ASK_OUTCOME_DECLINED, []),
        ([], _ASK.ASK_OUTCOME_EXHAUSTED, []),
        (
            [RunSuggestion(config=RunConfig.from_values({"param1": 3}), run_id="s1")],
            _ASK.ASK_OUTCOME_SUGGESTED,
            [("s1", {"param1": 3})],
        ),
    ],
    ids=["declined", "exhausted", "suggested"],
)
def test_ask_outcome_encodes_what_the_optimizer_answered(suggestions, outcome, encoded):
    optimizer = make_optimizer()
    optimizer.ask_n_runs.return_value = suggestions
    service = make_service([generation_task(1, ask_up_to=2), done_task(2)])

    run_exchange(service, optimizer)

    optimizer.ask_n_runs.assert_called_once_with(2)
    generation = sent_results(service)[1].generation
    assert generation.ask_outcome == outcome
    assert [
        (s.optimizer_run_id, json.loads(s.config_json)) for s in generation.suggestions
    ] == encoded


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


@pytest.mark.parametrize(
    "exit_error",
    [HandleAbandonedError, MailboxClosedError],
    ids=["abandoned", "closed"],
)
def test_a_lost_mailbox_raises_service_exited(exit_error):
    optimizer = make_optimizer()
    service = make_service([None], exit_error=exit_error)

    with pytest.raises(SchedulerServiceExitedError):
        run_exchange(service, optimizer)

    # The optimizer was never touched.
    assert optimizer.mock_calls == []


def test_cancelling_the_exchange_cancels_the_outstanding_poll():
    """A cancelled scheduler releases its long poll instead of dropping it."""
    optimizer = make_optimizer()
    handle = Mock(spec=MailboxHandle)
    polling = asyncio.Event()

    async def wait_async(timeout=None):
        polling.set()
        # Held open, so the cancel provably lands inside the poll.
        await asyncio.Event().wait()

    handle.wait_async.side_effect = wait_async
    service = Mock(spec=ServiceConnection)
    service.sweep_scheduler_next_task.return_value = handle
    exchange = SchedulerTaskExchange(  # type: ignore[arg-type]
        service, "scheduler-0", optimizer
    )

    async def cancel_while_polling():
        task = asyncio.ensure_future(exchange.run())
        await polling.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_while_polling())

    handle.cancel.assert_called_once_with()
    assert optimizer.mock_calls == []


def test_every_run_state_reaches_the_optimizer_unswapped():
    """Each update carries its own state, so a swapped pair must fail."""
    wire_to_state = {
        sspb.SWEEP_RUN_STATE_RUNNING: RunState.RUNNING,
        sspb.SWEEP_RUN_STATE_PENDING: RunState.PENDING,
        sspb.SWEEP_RUN_STATE_PREEMPTING: RunState.PREEMPTING,
        sspb.SWEEP_RUN_STATE_PREEMPTED: RunState.PREEMPTED,
        sspb.SWEEP_RUN_STATE_FINISHED: RunState.FINISHED,
        sspb.SWEEP_RUN_STATE_FAILED: RunState.FAILED,
        sspb.SWEEP_RUN_STATE_CRASHED: RunState.CRASHED,
        sspb.SWEEP_RUN_STATE_KILLED: RunState.KILLED,
        # Unrecognized by this client version, read as alive.
        sspb.SWEEP_RUN_STATE_UNKNOWN: RunState.UNKNOWN,
    }
    updates = {f"r{wire}": wire for wire in wire_to_state}
    expected = {f"r{wire}": state for wire, state in wire_to_state.items()}

    optimizer = make_optimizer()
    told: dict[str, RunState] = {}
    optimizer.tell_run.side_effect = lambda run_id, data: told.update(
        {run_id: data.state}
    )
    service = make_service([generation_task(1, updates=updates), done_task(2)])

    run_exchange(service, optimizer)

    assert told == expected


def test_a_terminating_optimizer_is_not_asked_for_more_runs():
    """Terminate wins over the ask, so the sweep stops at its own word."""
    optimizer = make_optimizer()
    optimizer.should_terminate_sweep.return_value = True
    optimizer.prune_runs.return_value = ["r1"]
    service = make_service(
        [
            generation_task(
                1,
                updates={"r1": sspb.SWEEP_RUN_STATE_RUNNING},
                ask_up_to=3,
                prune_candidates=["r1"],
            ),
            done_task(2),
        ]
    )

    run_exchange(service, optimizer)

    generation = sent_results(service)[1].generation
    assert generation.terminate is True
    assert list(generation.prune) == ["r1"]
    optimizer.ask_n_runs.assert_not_called()
    assert generation.ask_outcome == (
        sspb.SweepSchedulerClientGenerationResult.ASK_OUTCOME_UNSPECIFIED
    )


_DONE = sspb.SweepSchedulerServerDoneTask


@pytest.mark.parametrize(
    ("reason", "summary", "is_error"),
    [
        # An unset reason is not an error: the sweep may simply be over.
        (_DONE.REASON_UNSPECIFIED, "stopped", False),
        (_DONE.REASON_TERMINATED, "terminated the sweep", False),
        (_DONE.REASON_SWEEP_FINISHED, "finished", False),
        (_DONE.REASON_SWEEP_NOT_FOUND, "deleted", True),
        (_DONE.REASON_FATAL_ERROR, "fatal error", True),
        (_DONE.REASON_OPTIMIZER_ERROR, "optimizer failed", True),
        (_DONE.REASON_SHUTDOWN, "was stopped", False),
    ],
)
def test_describe_done_marks_errors(reason, summary, is_error):
    message, error = describe_done(_DONE(reason=reason))
    detailed, _ = describe_done(_DONE(reason=reason, message="42 runs"))

    assert summary in message
    assert error is is_error
    assert detailed == f"{message} (42 runs)"


# --- ServiceConnection's scheduler requests -------------------------------
#
# The three methods below are the client half of the socket routes in
# core/pkg/server/connection.go: they put one oneof on the wire and map the
# response back. A wrong oneof or a wrong response field would be invisible
# to the tests above, which mock ServiceConnection out entirely.


@pytest.fixture
def scheduler_service(monkeypatch) -> tuple[ServiceConnection, Mock]:
    """A ServiceConnection over a mocked socket client."""
    client = Mock(spec=ServiceClient)
    # Spec'd, or `deliver`'s AsyncMock would make the handle's `map` async
    # too and the mapped handle would silently be a coroutine.
    client.deliver.return_value = Mock(spec=MailboxHandle)

    # The finalizer starts a daemon thread and has no part in these requests.
    monkeypatch.setattr(service_connection, "ServiceFinalizer", Mock())
    service = ServiceConnection(asyncer=Mock(), client=client, proc=None)
    return service, client


def delivered(client: Mock) -> spb.ServerRequest:
    """The single request passed to `deliver`."""
    client.deliver.assert_called_once()
    return client.deliver.call_args.args[0]


def response_mapper(client: Mock):
    """The function the returned handle maps its response with."""
    return client.deliver.return_value.map.call_args.args[0]


async def test_init_sends_the_sweep_and_reads_the_init_response(
    scheduler_service,
):
    service, client = scheduler_service

    await service.init_sweep_scheduler(
        Settings(),
        entity="e",
        project="p",
        sweep_id="sweep-1",
        batch_size=3,
        poll_interval_seconds=7.5,
    )

    request = delivered(client)
    assert request.WhichOneof("server_request_type") == "sweep_scheduler_init"
    init = request.sweep_scheduler_init
    assert (init.entity, init.project, init.sweep_id) == ("e", "p", "sweep-1")
    assert init.batch_size == 3
    assert init.poll_interval_seconds == pytest.approx(7.5)

    # The handle must read the init response, not another oneof.
    expected = sspb.SweepSchedulerServerInitResponse(session_id="session-1")
    assert (
        response_mapper(client)(
            spb.ServerResponse(sweep_scheduler_init_response=expected)
        )
        == expected
    )


@pytest.mark.parametrize(
    "result",
    [
        None,
        sspb.SweepSchedulerClientTaskResult(
            warm_start=sspb.SweepSchedulerClientWarmStartResult(
                adoptions={"run-1": "opt-1"}
            )
        ),
    ],
    ids=["no result", "a result"],
)
async def test_next_task_sends_the_result_and_reads_the_task_response(
    scheduler_service,
    result,
):
    service, client = scheduler_service

    await service.sweep_scheduler_next_task("session-1", result)

    request = delivered(client)
    assert request.WhichOneof("server_request_type") == "sweep_scheduler_next_task"
    next_task = request.sweep_scheduler_next_task
    # The first task of a session answers no previous one.
    assert next_task.HasField("result") == (result is not None)
    assert next_task == sspb.SweepSchedulerClientNextTaskRequest(
        session_id="session-1",
        result=result,
    )

    expected = sspb.SweepSchedulerServerNextTaskResponse(
        warm_start=sspb.SweepSchedulerServerWarmStartTask(has_more=True)
    )
    assert (
        response_mapper(client)(
            spb.ServerResponse(sweep_scheduler_next_task_response=expected)
        )
        == expected
    )


async def test_stop_is_published_without_waiting_for_a_reply(scheduler_service):
    service, client = scheduler_service

    await service.stop_sweep_scheduler("session-1")

    client.publish.assert_called_once()
    request = client.publish.call_args.args[0]
    assert request.WhichOneof("server_request_type") == "sweep_scheduler_stop"
    assert request.sweep_scheduler_stop.session_id == "session-1"
    # The Done task answers the outstanding long poll; stop gets no reply of
    # its own, so waiting on one would hang the shutdown.
    client.deliver.assert_not_called()
