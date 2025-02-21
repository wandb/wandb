import asyncio
import unittest.mock
from typing import NoReturn

import pytest
import wandb.sdk.mailbox as mb
from wandb.proto import wandb_server_pb2 as spb


async def _loop_forever() -> NoReturn:
    while True:
        await asyncio.sleep(1)


def test_short_timeout_uses_blocking_wait():
    # We mock here as otherwise it is not possible to distinguish
    # the use of wait_or() from wait_async().
    handle = unittest.mock.Mock()
    handle.wait_or.return_value = "test-value"

    result = mb.wait_with_progress(
        handle,
        timeout=1,
        progress_after=2,
        display_progress=_loop_forever,
    )

    handle.wait_or.assert_called_once()
    _, kwargs = handle.wait_or.call_args
    assert kwargs["timeout"] == pytest.approx(1, rel=0.1)
    assert result == "test-value"


def test_delivered_returns_immediately():
    mailbox = mb.Mailbox()
    request1 = spb.ServerRequest()
    request2 = spb.ServerRequest()
    handle1 = mailbox.require_response(request1)
    handle2 = mailbox.require_response(request2)
    response1 = spb.ServerResponse(request_id=request1.request_id)
    response2 = spb.ServerResponse(request_id=request2.request_id)

    mailbox.deliver(response1)
    mailbox.deliver(response2)

    values = mb.wait_all_with_progress(
        [handle1, handle2],
        timeout=10,
        progress_after=1,
        display_progress=_loop_forever,
    )

    assert values == [response1, response2]


def test_wait_all_same_handle_ok():
    mailbox = mb.Mailbox()
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)
    mailbox.deliver(response)

    values = mb.wait_all_with_progress(
        [handle, handle, handle],
        timeout=10,
        progress_after=1,
        display_progress=_loop_forever,
    )

    assert values == [response, response, response]


def test_abandoned_raises_immediately():
    handle = mb.Mailbox().require_response(spb.ServerRequest())
    handle.abandon()

    with pytest.raises(mb.HandleAbandonedError):
        mb.wait_with_progress(
            handle,
            timeout=None,
            progress_after=1,
            display_progress=_loop_forever,
        )


def test_runs_and_cancels_display_callback():
    mailbox = mb.Mailbox()
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)
    cancelled = False

    async def deliver_handle():
        nonlocal cancelled
        mailbox.deliver(response)
        try:
            await _loop_forever()
        except asyncio.CancelledError:
            cancelled = True

    value = mb.wait_with_progress(
        handle,
        timeout=None,
        progress_after=0,
        display_progress=deliver_handle,
    )

    assert value is response
    assert cancelled


def test_times_out():
    handle = mb.Mailbox().require_response(spb.ServerRequest())

    with pytest.raises(TimeoutError):
        mb.wait_with_progress(
            handle,
            timeout=0.002,
            progress_after=0.001,
            display_progress=_loop_forever,
        )
