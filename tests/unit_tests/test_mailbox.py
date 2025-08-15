import math
import threading
import unittest.mock

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk import mailbox as mb
from wandb.sdk.lib import asyncio_manager
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


def test_wait_already_delivered(any_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)

    mailbox.deliver(response)
    handle_response = handle.wait_or(timeout=any_timeout)

    assert response is handle_response


def test_wait_async_already_delivered(any_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)

    mailbox.deliver(response)
    handle_response = asyncer.run(
        lambda: handle.wait_async(timeout=any_timeout),
    )

    assert response is handle_response


def test_wait_abandoned(any_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer)
    handle = mailbox.require_response(spb.ServerRequest())

    handle.abandon()
    with pytest.raises(mb.HandleAbandonedError):
        handle.wait_or(timeout=any_timeout)


def test_wait_async_abandoned(any_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer)
    handle = mailbox.require_response(spb.ServerRequest())

    handle.abandon()
    with pytest.raises(mb.HandleAbandonedError):
        asyncer.run(lambda: handle.wait_async(timeout=any_timeout))


def test_wait_timeout(immediate_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer)
    handle = mailbox.require_response(spb.ServerRequest())

    with pytest.raises(TimeoutError):
        handle.wait_or(timeout=immediate_timeout)


def test_wait_async_timeout(immediate_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer)
    handle = mailbox.require_response(spb.ServerRequest())

    with pytest.raises(TimeoutError):
        asyncer.run(lambda: handle.wait_async(timeout=immediate_timeout))


def test_wait_invalid_timeout(invalid_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer)
    handle = mailbox.require_response(spb.ServerRequest())

    with pytest.raises(ValueError, match="Timeout must be finite or None."):
        handle.wait_or(timeout=invalid_timeout)


async def test_wait_async_invalid_timeout(invalid_timeout, asyncer):
    mailbox = mb.Mailbox(asyncer)
    handle = mailbox.require_response(spb.ServerRequest())

    with pytest.raises(ValueError, match="Timeout must be finite or None."):
        asyncer.run(lambda: handle.wait_async(timeout=invalid_timeout))


@pytest.mark.parametrize("kind", ["deliver", "abandon"])
def test_unblocks_wait(kind, asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)

    about_to_wait = threading.Event()
    done_waiting = threading.Event()
    abandoned = threading.Event()

    def wait_for_handle():
        about_to_wait.set()
        try:
            handle.wait_or(timeout=5)
            done_waiting.set()
        except mb.HandleAbandonedError:
            abandoned.set()

    t = threading.Thread(target=wait_for_handle)
    t.start()

    # Once we observe the event, it's very likely (but not guaranteed)
    # that the thread is blocked in `wait_or`.
    about_to_wait.wait()

    if kind == "deliver":
        mailbox.deliver(response)
        assert done_waiting.wait(timeout=1)
    else:
        handle.abandon()
        assert abandoned.wait(timeout=1)


# @pytest.mark.parametrize("kind", ["deliver", "abandon"])
# async def test_unblocks_wait_async(kind, asyncer):
#     mailbox = mb.Mailbox(asyncer)
#     request = spb.ServerRequest()
#     handle = mailbox.require_response(request)
#     response = spb.ServerResponse(request_id=request.request_id)

#     about_to_wait = asyncio.Event()
#     done_waiting = asyncio.Event()
#     abandoned = asyncio.Event()

#     async def wait_for_handle():
#         about_to_wait.set()
#         try:
#             await handle.wait_async(timeout=5)
#             done_waiting.set()
#         except mb.HandleAbandonedError:
#             abandoned.set()

#     async with asyncio_compat.open_task_group() as task_group:
#         task_group.start_soon(wait_for_handle())

#         # When we observe the event, wait_for_handle should be suspended
#         # immediately before the wait_async. Using sleep(0) a few times lets
#         # wait_for_handle progress just far enough to make sure it's blocked on
#         # the internal `evt.wait()` instead of short-circuiting.
#         await about_to_wait.wait()
#         await asyncio.sleep(0)
#         await asyncio.sleep(0)
#         await asyncio.sleep(0)

#         if kind == "deliver":
#             mailbox.deliver(response)
#             asyncio.wait_for(done_waiting.wait(), timeout=1)
#         else:
#             handle.abandon()
#             asyncio.wait_for(abandoned.wait(), timeout=1)


def test_require_response_sets_address(asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    mailbox.require_response(request)

    assert len(request.request_id) == 12


def test_require_response_sets_mailbox_slot(asyncer):
    mailbox = mb.Mailbox(asyncer)
    record = pb.Record()
    mailbox.require_response(record)

    assert len(record.control.mailbox_slot) == 12


def test_require_response_raises_if_address_is_set(asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    mailbox.require_response(request)

    with pytest.raises(ValueError, match="already has an address"):
        mailbox.require_response(request)


def test_require_response_raises_if_mailbox_slot_is_set(asyncer):
    mailbox = mb.Mailbox(asyncer)
    record = pb.Record()
    mailbox.require_response(record)

    with pytest.raises(ValueError, match="already has an address"):
        mailbox.require_response(record)


def test_require_response_raises_if_closed(asyncer):
    mailbox = mb.Mailbox(asyncer)
    mailbox.close()

    with pytest.raises(mb.MailboxClosedError):
        mailbox.require_response(spb.ServerRequest())


def test_deliver_unknown_address(asyncer):
    mailbox = mb.Mailbox(asyncer)
    response = spb.ServerResponse()
    response.request_id = "unknown"

    # Should pass.
    mailbox.deliver(response)


def test_deliver_no_address(wandb_caplog, asyncer):
    mailbox = mb.Mailbox(asyncer)

    mailbox.deliver(spb.ServerResponse())

    assert "Received response with no mailbox slot" in wandb_caplog.text


def test_deliver_after_abandon(asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)

    handle.abandon()
    mailbox.deliver(spb.ServerResponse(request_id=request.request_id))

    assert handle.check() is None


def test_deliver_twice_raises_error(asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    assert isinstance(handle, MailboxResponseHandle)
    handle.deliver(spb.ServerResponse(request_id=request.request_id))

    with pytest.raises(ValueError, match="has already been delivered"):
        handle.deliver(spb.ServerResponse(request_id=request.request_id))


def test_close_abandons_handles(asyncer):
    mailbox = mb.Mailbox(asyncer)
    handle1 = mailbox.require_response(spb.ServerRequest())
    handle2 = mailbox.require_response(spb.ServerRequest())

    mailbox.close()

    assert isinstance(handle1, MailboxResponseHandle)
    assert isinstance(handle2, MailboxResponseHandle)
    assert handle1._abandoned
    assert handle2._abandoned


def test_cancel_abandons_handle(asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    iface_mock = unittest.mock.Mock()

    handle.cancel(iface_mock)

    iface_mock.publish_cancel.assert_called_once_with(request.request_id)
    assert isinstance(handle, MailboxResponseHandle)
    assert handle._abandoned


def test_check_returns_none_before_delivered(asyncer):
    mailbox = mb.Mailbox(asyncer)
    handle = mailbox.require_response(spb.ServerRequest())

    assert handle.check() is None


def test_check_returns_result(asyncer):
    mailbox = mb.Mailbox(asyncer)
    request = spb.ServerRequest()
    handle = mailbox.require_response(request)
    response = spb.ServerResponse(request_id=request.request_id)
    mailbox.deliver(response)

    assert handle.check() is response
