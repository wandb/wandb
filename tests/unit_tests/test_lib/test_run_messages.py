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
    rm = run_messages._RunMessagesImpl(fake_interface)

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(rm.loop())

        # Pretend first message batch happens at 1 second,
        # then the run exits immediately after.
        await asyncio.sleep(1)
        fake_messages.put_nowait(_result("warning 1", "warning 2", "warning 3"))
        fake_messages.put_nowait(_result())

        await rm.stop(timeout=5)

    mock_wandb_log.assert_warned("warning 1")
    mock_wandb_log.assert_warned("warning 2")
    mock_wandb_log.assert_warned("warning 3")
    assert looptime == 1  # no extra sleeping


@pytest.mark.looptime
async def test_stop_warns_on_timeout(
    looptime: LoopTimeProxy,
    fake_interface: Mock,
    wandb_caplog: pytest.LogCaptureFixture,
):
    rm = run_messages._RunMessagesImpl(fake_interface)

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(rm.loop())
        await rm.stop(timeout=10)

    assert "Timed out waiting for messages" in wandb_caplog.text
    assert looptime == 10


@pytest.mark.looptime
async def test_rate_limits(
    looptime: LoopTimeProxy,
    fake_messages: asyncio.Queue[pb.Result],
    fake_interface: Mock,
):
    rm = run_messages._RunMessagesImpl(fake_interface)

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(rm.loop())

        fake_messages.put_nowait(_result("message 1"))  # immediate
        fake_messages.put_nowait(_result("message 2"))  # after 0.1s
        fake_messages.put_nowait(_result("message 3"))  # after 0.2s
        fake_messages.put_nowait(_result())  # after 0.3s

        await rm.stop(timeout=5)

    assert looptime == 0.3
