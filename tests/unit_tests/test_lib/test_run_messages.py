import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from looptime import LoopTimeProxy
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib import asyncio_compat, run_messages

from tests.fixtures.mock_wandb_log import MockWandbLog


@pytest_asyncio.fixture
async def fake_messages() -> asyncio.Queue[pb.Result]:
    """The queue of internal message responses to return in tests."""
    return asyncio.Queue()


@pytest_asyncio.fixture
async def fake_interface(fake_messages: asyncio.Queue[pb.Result]) -> Mock:
    """Mock interface that returns fake_messages from deliver_async."""

    async def next_message(*, timeout: float) -> pb.Result:
        result = await asyncio.wait_for(fake_messages.get(), timeout=timeout)
        fake_messages.task_done()  # needed for join() in tests
        return result

    handle = Mock()
    handle.wait_async = next_message

    interface = Mock()
    interface.deliver_async = AsyncMock(return_value=handle)

    return interface


def _result(*warnings: str) -> pb.Result:
    result = pb.Result()
    result.response.internal_messages_response.messages.warning.extend(warnings)
    return result


@pytest.mark.looptime
async def test_prints_warnings(
    looptime: LoopTimeProxy,
    fake_messages: asyncio.Queue[pb.Result],
    fake_interface: Mock,
    mock_wandb_log: MockWandbLog,
):
    rm = run_messages._RunMessagesImpl(fake_interface, poll_interval=10)

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(rm.loop())

        # Let loop() process one message:
        fake_messages.put_nowait(_result("warning 1", "warning 2", "warning 3"))
        await fake_messages.join()

        # This message gets processed by stop():
        fake_messages.put_nowait(_result("final warning"))
        await rm.stop(timeout=5)

    mock_wandb_log.assert_warned("warning 1")
    mock_wandb_log.assert_warned("warning 2")
    mock_wandb_log.assert_warned("warning 3")
    mock_wandb_log.assert_warned("final warning")
    assert looptime == 0  # No sleeping should have happened.


@pytest.mark.looptime
async def test_stop_warns_on_loop_timeout(
    fake_interface: Mock,
    wandb_caplog: pytest.LogCaptureFixture,
):
    rm = run_messages._RunMessagesImpl(fake_interface, poll_interval=10)

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(rm.loop())
        await rm.stop(timeout=-1)  # time out immediately

    assert "Timed out waiting for messages" in wandb_caplog.text


@pytest.mark.looptime
async def test_stop_warns_on_handle_timeout(
    fake_interface: Mock,
    wandb_caplog: pytest.LogCaptureFixture,
):
    rm = run_messages._RunMessagesImpl(fake_interface, poll_interval=10)

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(rm.loop())
        await rm.stop(timeout=7)  # times out waiting on fake_messages

    assert "Timed out waiting for messages" in wandb_caplog.text


@pytest.mark.looptime
async def test_rate_limits(
    looptime: LoopTimeProxy,
    fake_messages: asyncio.Queue[pb.Result],
    fake_interface: Mock,
):
    rm = run_messages._RunMessagesImpl(fake_interface, poll_interval=10)

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(rm.loop())

        fake_messages.put_nowait(_result())  # immediate
        fake_messages.put_nowait(_result())  # at 10s
        fake_messages.put_nowait(_result())  # at 20s
        await fake_messages.join()  # let the loop process everything

        fake_messages.put_nowait(_result())  # last loop() iteration
        fake_messages.put_nowait(_result())  # for stop()
        await rm.stop(timeout=5)

    assert looptime == 20
