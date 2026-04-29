import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib import asyncio_manager, run_messages

from tests.fixtures.mock_wandb_log import MockWandbLog


@pytest.fixture(autouse=True)
def fake_now(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patched time.monotonic() that returns 0 by default."""
    now = MagicMock()
    now.return_value = 0
    monkeypatch.setattr(run_messages, "_NOW", now)
    return now


@pytest.fixture(autouse=True)
def fake_sleep(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patched asyncio.sleep() that blocks forever by default."""

    async def block(duration: float) -> None:
        _ = duration
        await asyncio.Event().wait()

    sleep = AsyncMock()
    sleep.side_effect = block
    monkeypatch.setattr(run_messages, "_SLEEP", sleep)

    return sleep


@pytest.fixture
def fake_messages() -> AsyncMock:
    """Patched MailboxHandle.wait_async() that returns an empty Result."""
    return AsyncMock(return_value=pb.Result())


@pytest.fixture
def fake_interface(fake_messages: AsyncMock) -> Mock:
    """Mock interface that returns fake_messages from deliver_async."""
    handle = Mock()
    handle.wait_async = fake_messages

    interface = Mock()
    interface.deliver_async = AsyncMock(return_value=handle)

    return interface


@pytest.fixture(scope="module")
def asyncer():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    try:
        yield asyncer
    finally:
        asyncer.join()


def _make_messages_result(*warnings: str) -> pb.Result:
    result = pb.Result()
    result.response.internal_messages_response.messages.warning.extend(warnings)
    return result


def test_prints_warnings(
    asyncer: asyncio_manager.AsyncioManager,
    fake_messages: AsyncMock,
    fake_interface: Mock,
    mock_wandb_log: MockWandbLog,
):
    fake_messages.side_effect = [
        _make_messages_result("warning 1", "warning 2", "warning 3"),
        _make_messages_result(),
    ]

    rm = run_messages.RunMessages(asyncer, fake_interface)
    rm.start()
    rm.stop(timeout=5)

    mock_wandb_log.assert_warned("warning 1")
    mock_wandb_log.assert_warned("warning 2")
    mock_wandb_log.assert_warned("warning 3")


def test_stop_does_final_poll(
    asyncer: asyncio_manager.AsyncioManager,
    fake_messages: AsyncMock,
    fake_interface: Mock,
    mock_wandb_log: MockWandbLog,
):
    fake_messages.side_effect = [
        _make_messages_result(),
        _make_messages_result("final warning"),
    ]

    rm = run_messages.RunMessages(asyncer, fake_interface)
    rm.start()
    rm.stop(timeout=5)

    mock_wandb_log.assert_warned("final warning")


def test_stop_warns_on_loop_timeout(
    asyncer: asyncio_manager.AsyncioManager,
    fake_messages: AsyncMock,
    fake_interface: Mock,
    wandb_caplog: pytest.LogCaptureFixture,
):
    fake_messages.side_effect = [
        _make_messages_result(),
        _make_messages_result(),
    ]

    rm = run_messages.RunMessages(asyncer, fake_interface)
    rm.start()
    rm.stop(timeout=-1)  # time out immediately

    assert "Timed out waiting for messages" in wandb_caplog.text


def test_stop_warns_on_handle_timeout(
    asyncer: asyncio_manager.AsyncioManager,
    fake_messages: AsyncMock,
    fake_interface: Mock,
    wandb_caplog: pytest.LogCaptureFixture,
):
    fake_messages.side_effect = [
        _make_messages_result(),
        TimeoutError(),
    ]

    rm = run_messages.RunMessages(asyncer, fake_interface)
    rm.start()
    rm.stop(timeout=5)

    assert "Timed out waiting for messages" in wandb_caplog.text


def test_sleeps_for_remaining_interval(
    asyncer: asyncio_manager.AsyncioManager,
    fake_sleep: AsyncMock,
    fake_now: MagicMock,
    fake_messages: AsyncMock,
    fake_interface: Mock,
):
    fake_now.side_effect = [0, 3]  # pretend 3 seconds pass waiting for messages
    fake_messages.side_effect = [
        _make_messages_result(),
        _make_messages_result(),
    ]

    rm = run_messages.RunMessages(asyncer, fake_interface, poll_interval=10)
    rm.start()
    rm.stop(timeout=5)

    # Polling interval is 10, and 3 seconds passed, so 7 remain.
    fake_sleep.assert_called_once_with(7)
