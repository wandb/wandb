from __future__ import annotations

import asyncio
from typing import Any, Coroutine

import pytest
from wandb.sdk.lib import asyncio_compat


async def _fail_after_timeout(
    coro: Coroutine[Any, Any, Any],
    failure_message: str,
) -> None:
    try:
        await asyncio.wait_for(coro, timeout=1)
    except (asyncio.TimeoutError, TimeoutError) as e:
        raise AssertionError(failure_message) from e


async def _yield() -> None:
    """Allow other scheduled tasks to run."""
    await asyncio.sleep(0)


class _TaskGroupTester:
    def __init__(self) -> None:
        self._before_exit = asyncio.Event()
        self._after_exit = asyncio.Event()

    def start(
        self,
        subtasks: list[Coroutine[Any, Any, Any]],
        main_task: Coroutine[Any, Any, Any] | None = None,
    ) -> None:
        """Start the tester.

        This schedules a parallel task that opens a task group, adds
        the given subtasks to it, and run the main task in the context
        manager body.
        """

        async def run():
            try:
                async with asyncio_compat.open_task_group() as task_group:
                    for subtask in subtasks:
                        task_group.start_soon(subtask)

                    if main_task:
                        await main_task

                    self._before_exit.set()
            finally:
                self._after_exit.set()

        asyncio.create_task(run())

    async def assert_blocked_on_exit(self) -> None:
        """Assert the tester's blocked waiting for the task group to exit."""
        await _fail_after_timeout(
            self._before_exit.wait(),
            "Didn't reach end of task group context manager.",
        )
        assert not self._after_exit.is_set()

    async def assert_exits(self) -> None:
        """Assert the tester has exited."""
        await _fail_after_timeout(
            self._after_exit.wait(),
            "Didn't exit task group.",
        )


class _CancellationDetector:
    def __init__(self) -> None:
        self._cancelled = asyncio.Event()

    async def expect_cancelled(self) -> None:
        """A coroutine that detects if it is cancelled."""
        try:
            await asyncio.sleep(1)
            raise AssertionError("Expected to get cancelled.")
        except asyncio.CancelledError:
            self._cancelled.set()

    async def assert_cancelled(self) -> None:
        """Assert the detector's task got started and cancelled.

        This will not detect if the task is cancelled before it is scheduled.
        """
        await _fail_after_timeout(
            self._cancelled.wait(),
            "Task didn't get cancelled, or didn't start.",
        )


class _TestError(Exception):
    """Intentional error raised in a test."""


def test_compat_run_in_asyncio_context():
    success = False

    async def internal_wandb_thing():
        nonlocal success
        success = True

    async def i_use_wandb_in_asyncio():
        # NOTE: Using asyncio.run() inside an asyncio loop fails.
        asyncio_compat.run(internal_wandb_thing)

    asyncio.run(i_use_wandb_in_asyncio())

    assert success


@pytest.mark.asyncio
async def test_cancel_on_exit_normal():
    cd = _CancellationDetector()

    with asyncio_compat.cancel_on_exit(cd.expect_cancelled()):
        await _yield()

    await cd.assert_cancelled()


@pytest.mark.asyncio
async def test_cancel_on_exit_error_in_body():
    cd = _CancellationDetector()

    with pytest.raises(_TestError):
        with asyncio_compat.cancel_on_exit(cd.expect_cancelled()):
            await _yield()
            raise _TestError()

    await cd.assert_cancelled()


@pytest.mark.asyncio
async def test_cancel_on_exit_error_in_task():
    async def fail():
        await _yield()
        raise _TestError()

    with pytest.raises(_TestError):
        with asyncio_compat.cancel_on_exit(fail()):
            await _yield()
            await _yield()


@pytest.mark.asyncio
async def test_task_group_waits():
    tester = _TaskGroupTester()
    event = asyncio.Event()

    tester.start(subtasks=[event.wait()])

    await tester.assert_blocked_on_exit()
    event.set()
    await tester.assert_exits()


@pytest.mark.asyncio
async def test_task_group_cancels_on_body_error():
    async def fail():
        await _yield()
        raise _TestError()

    tester = _TaskGroupTester()
    cd = _CancellationDetector()

    tester.start(
        subtasks=[cd.expect_cancelled()],
        main_task=fail(),
    )

    await tester.assert_exits()
    await cd.assert_cancelled()


@pytest.mark.asyncio
async def test_task_group_cancels_on_subtask_error():
    async def fail():
        await _yield()
        raise _TestError()

    tester = _TaskGroupTester()
    cd1 = _CancellationDetector()
    cd2 = _CancellationDetector()

    tester.start(
        subtasks=[
            cd1.expect_cancelled(),
            fail(),
            cd2.expect_cancelled(),
        ]
    )

    await tester.assert_exits()
    await cd1.assert_cancelled()
    await cd2.assert_cancelled()
