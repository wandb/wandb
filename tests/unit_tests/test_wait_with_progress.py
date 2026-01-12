from __future__ import annotations

import asyncio
from typing import NoReturn

import pytest
import wandb.sdk.mailbox as mb
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager


async def _loop_forever() -> NoReturn:
    while True:
        await asyncio.sleep(1)


@pytest.fixture(scope="module")
def asyncer():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    try:
        yield asyncer
    finally:
        asyncer.join()


async def _cancel_noop(id: str) -> None:
    _ = id


def test_delivered_returns_immediately(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request1 = spb.ServerRequest()
    request2 = spb.ServerRequest()
    handle1 = mailbox.require_response(request1)
    handle2 = mailbox.require_response(request2)
    response1 = spb.ServerResponse(request_id=request1.request_id)
    response2 = spb.ServerResponse(request_id=request2.request_id)

    asyncer.run(lambda: mailbox.deliver(response1))
    asyncer.run(lambda: mailbox.deliver(response2))

    values = mb.wait_all_with_progress(
        [handle1, handle2],
        timeout=10,
        display_progress=_loop_forever,
    )

    assert values == [response1, response2]


def test_wait_all_same_handle_ok(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)
    asyncer.run(lambda: mailbox.deliver(response))

    values = mb.wait_all_with_progress(
        [handle, handle, handle],
        timeout=10,
        display_progress=_loop_forever,
    )

    assert values == [response, response, response]


def test_abandoned_raises_immediately(asyncer):
    handle = mb.Mailbox(
        asyncer,
        _cancel_noop,
    ).require_response(spb.ServerRequest())
    handle.cancel()

    with pytest.raises(mb.HandleAbandonedError):
        mb.wait_with_progress(
            handle,
            timeout=None,
            display_progress=_loop_forever,
        )


def test_runs_and_cancels_display_callback(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)
    cancelled = False

    async def deliver_handle():
        nonlocal cancelled
        await mailbox.deliver(response)
        try:
            await _loop_forever()
        except asyncio.CancelledError:
            cancelled = True

    value = mb.wait_with_progress(
        handle,
        timeout=None,
        display_progress=deliver_handle,
    )

    assert value is response
    assert cancelled


def test_times_out(asyncer):
    handle = mb.Mailbox(
        asyncer,
        _cancel_noop,
    ).require_response(spb.ServerRequest())

    with pytest.raises(TimeoutError):
        mb.wait_with_progress(
            handle,
            timeout=0.002,
            display_progress=_loop_forever,
        )
