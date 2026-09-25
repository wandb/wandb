"""Unit tests of the sweep scheduler's client-side IPC, in pure Python.

`ServiceConnection` here talks to a mocked socket client: no wandb-core
process or backend is involved. For the real IPC path end-to-end, see
tests/system_tests/test_sweep/test_sweep_scheduler_e2e.py.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_sweep_scheduler_pb2 as sspb
from wandb.sdk.lib.service import service_connection
from wandb.sdk.lib.service.service_client import ServiceClient
from wandb.sdk.lib.service.service_connection import ServiceConnection
from wandb.sdk.mailbox import MailboxHandle
from wandb.sdk.wandb_settings import Settings

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
