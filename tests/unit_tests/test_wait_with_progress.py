import asyncio
import unittest.mock
from typing import NoReturn

import pytest
import wandb.sdk.mailbox as mb
from wandb.proto import wandb_internal_pb2 as pb


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
    handle1 = mb.MailboxHandle("address1")
    handle2 = mb.MailboxHandle("address2")
    result1 = pb.Result(uuid="abc")
    result2 = pb.Result(uuid="xyz")
    handle1.deliver(result1)
    handle2.deliver(result2)

    values = mb.wait_all_with_progress(
        [handle1, handle2],
        timeout=10,
        progress_after=1,
        display_progress=_loop_forever,
    )

    assert values == [result1, result2]


def test_wait_all_same_handle_ok():
    handle = mb.MailboxHandle("address")
    result = pb.Result(uuid="abc")
    handle.deliver(result)

    values = mb.wait_all_with_progress(
        [handle, handle, handle],
        timeout=10,
        progress_after=1,
        display_progress=_loop_forever,
    )

    assert values == [result, result, result]


def test_abandoned_raises_immediately():
    handle = mb.MailboxHandle("address")
    handle.abandon()

    with pytest.raises(mb.HandleAbandonedError):
        mb.wait_with_progress(
            handle,
            timeout=None,
            progress_after=1,
            display_progress=_loop_forever,
        )


def test_runs_and_cancels_display_callback():
    handle = mb.MailboxHandle("address")
    result = pb.Result()
    cancelled = False

    async def deliver_handle():
        nonlocal cancelled
        handle.deliver(result)
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

    assert value is result
    assert cancelled


def test_times_out():
    handle = mb.MailboxHandle("address")

    with pytest.raises(TimeoutError):
        mb.wait_with_progress(
            handle,
            timeout=0.002,
            progress_after=0.001,
            display_progress=_loop_forever,
        )
