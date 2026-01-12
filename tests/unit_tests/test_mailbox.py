from __future__ import annotations

import asyncio
import math
import unittest.mock

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk import mailbox as mb
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.mailbox.mailbox_handle import HandleAbandonedError
from wandb.sdk.mailbox.response_handle import MailboxResponseHandle


@pytest.fixture(params=[-9.4, -1, 0, 99.1, None])
def any_timeout(request):
    """An arbitrary timeout value.

    - A negative number
    - Negative one (which may be special)
    - Zero (which may be special)
    - A positive number
    - None
    """
    return request.param


@pytest.fixture(params=[-3.2, -1, 0])
def immediate_timeout(request):
    """A timeout value that should be an immediate timeout."""
    return request.param


@pytest.fixture(params=[math.inf, math.nan])
def invalid_timeout(request):
    """A value that cannot be used as a timeout."""
    return request.param


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


def test_wait_already_delivered(any_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)

    asyncer.run(lambda: mailbox.deliver(response))
    handle_response = handle.wait_or(timeout=any_timeout)

    assert response is handle_response


def test_wait_abandoned(any_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    handle = mailbox.require_response(spb.ServerRequest())

    handle.cancel()
    with pytest.raises(mb.HandleAbandonedError):
        handle.wait_or(timeout=any_timeout)


def test_wait_timeout(immediate_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    handle = mailbox.require_response(spb.ServerRequest())

    with pytest.raises(TimeoutError):
        handle.wait_or(timeout=immediate_timeout)


def test_wait_invalid_timeout(invalid_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    handle = mailbox.require_response(spb.ServerRequest())

    with pytest.raises(ValueError, match="Timeout must be finite or None."):
        handle.wait_or(timeout=invalid_timeout)


@pytest.mark.parametrize("kind", ["deliver", "abandon"])
def test_unblocks_wait_async(kind, asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)

    async def new_event():
        """Create an asyncio.Event while inside the asyncio event loop."""
        return asyncio.Event()

    delivered = asyncer.run(new_event)
    abandoned = asyncer.run(new_event)

    async def wait_for_handle() -> None:
        try:
            await handle.wait_async(timeout=5)
            delivered.set()
        except mb.HandleAbandonedError:
            abandoned.set()

    async def wait_event(event: asyncio.Event) -> None:
        await asyncio.wait_for(event.wait(), timeout=1)

    asyncer.run_soon(wait_for_handle)

    if kind == "deliver":
        asyncer.run(lambda: mailbox.deliver(response))
        asyncer.run(lambda: wait_event(delivered))
    else:
        handle.cancel()
        asyncer.run(lambda: wait_event(abandoned))


def test_require_response_sets_address(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    mailbox.require_response(request)

    assert len(request.request_id) == 12


def test_require_response_sets_mailbox_slot(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    record = pb.Record()
    mailbox.require_response(record)

    assert len(record.control.mailbox_slot) == 12


def test_require_response__record_publish(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    request.record_publish.exit.exit_code = 0
    mailbox.require_response(request)

    assert len(request.request_id) == 12
    assert request.record_publish.control.mailbox_slot == request.request_id


def test_require_response__record_communicate(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    request.record_communicate.exit.exit_code = 0
    mailbox.require_response(request)

    assert len(request.request_id) == 12
    assert request.record_communicate.control.mailbox_slot == request.request_id


def test_require_response_raises_if_address_is_set(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    mailbox.require_response(request)

    with pytest.raises(ValueError, match="already has an address"):
        mailbox.require_response(request)


def test_require_response_raises_if_mailbox_slot_is_set(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    record = pb.Record()
    mailbox.require_response(record)

    with pytest.raises(ValueError, match="already has an address"):
        mailbox.require_response(record)


def test_require_response_raises_if_closed(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    mailbox.close()

    with pytest.raises(mb.MailboxClosedError):
        mailbox.require_response(spb.ServerRequest())


def test_deliver_unknown_address(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    response = spb.ServerResponse()
    response.request_id = "unknown"

    # Should pass.
    asyncer.run(lambda: mailbox.deliver(response))


def test_deliver_no_address(wandb_caplog, asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)

    asyncer.run(lambda: mailbox.deliver(spb.ServerResponse()))

    assert "Received response with no mailbox slot" in wandb_caplog.text


def test_deliver_after_abandon(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    assert isinstance(handle, MailboxResponseHandle)

    handle.abandon()
    asyncer.run(
        lambda: handle.deliver(
            spb.ServerResponse(request_id=request.request_id),
        )
    )

    with pytest.raises(HandleAbandonedError):
        handle.wait_or(timeout=1)


def test_deliver_twice_raises_error(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    assert isinstance(handle, MailboxResponseHandle)
    asyncer.run(
        lambda: handle.deliver(
            spb.ServerResponse(request_id=request.request_id),
        )
    )

    with pytest.raises(ValueError, match="has already been delivered"):
        asyncer.run(
            lambda: handle.deliver(
                spb.ServerResponse(request_id=request.request_id),
            )
        )


def test_close_abandons_handles(asyncer):
    mailbox = mb.Mailbox(asyncer, _cancel_noop)
    handle1 = mailbox.require_response(spb.ServerRequest())
    handle2 = mailbox.require_response(spb.ServerRequest())

    mailbox.close()

    with pytest.raises(HandleAbandonedError):
        handle1.wait_or(timeout=1)
    with pytest.raises(HandleAbandonedError):
        handle2.wait_or(timeout=1)


def test_cancel_abandons_handle(asyncer):
    mock_cancel = unittest.mock.MagicMock()
    mailbox = mb.Mailbox(asyncer, mock_cancel)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)

    handle.cancel()

    with pytest.raises(HandleAbandonedError):
        handle.wait_or(timeout=1)
    mock_cancel.assert_called_once_with(request.request_id)
