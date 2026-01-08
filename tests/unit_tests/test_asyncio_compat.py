from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

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

    async with asyncio_compat.cancel_on_exit(cd.expect_cancelled()):
        await _yield()

    await cd.assert_cancelled()


@pytest.mark.asyncio
async def test_cancel_on_exit_error_in_body():
    cd = _CancellationDetector()

    with pytest.raises(_TestError):
        async with asyncio_compat.cancel_on_exit(cd.expect_cancelled()):
            await _yield()
            raise _TestError()

    await cd.assert_cancelled()


@pytest.mark.asyncio
async def test_cancel_on_exit_error_in_task():
    async def fail():
        await _yield()
        raise _TestError()

    with pytest.raises(_TestError):
        async with asyncio_compat.cancel_on_exit(fail()):
            await _yield()
            await _yield()


@pytest.mark.asyncio
async def test_cancel_on_exit_errors_everywhere():
    async def fail(msg: str):
        raise _TestError(msg)

    with pytest.raises(_TestError, match="inner") as exc:
        async with asyncio_compat.cancel_on_exit(fail("outer")):
            # Ensure the outer task has already failed before raising
            # an error. We want to make sure that the inner error still
            # takes priority.
            await _yield()
            await fail("inner")

    # The outer error shouldn't appear as the context or cause of the inner one,
    # or else the default stacktrace will say "During handling of the above
    # exception, another exception occurred".
    assert not exc.value.__context__
    assert not exc.value.__cause__


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


@pytest.mark.asyncio
async def test_task_group_exit_timeout():
    with pytest.raises(TimeoutError):
        async with asyncio_compat.open_task_group(exit_timeout=0) as group:
            group.start_soon(asyncio.sleep(5))


@pytest.mark.asyncio
async def test_task_group_empty_ok():
    async with asyncio_compat.open_task_group():
        pass


@pytest.mark.asyncio
async def test_race_cancels_unfinished_tasks():
    completion_order = []
    event = asyncio.Event()

    async def wait_for_event():
        await event.wait()
        completion_order.append("finished first")

    async def set_event_then_wait_forever():
        event.set()

        try:
            await asyncio.sleep(99)
        except asyncio.CancelledError:
            completion_order.append("cancelled second")
            raise

    await asyncio_compat.race(
        wait_for_event(),
        set_event_then_wait_forever(),
    )

    assert completion_order == ["finished first", "cancelled second"]


@pytest.mark.asyncio
async def test_race_raises_first_error():
    event = asyncio.Event()

    async def raise_first():
        event.set()
        raise _TestError("first")

    async def return_first():
        pass

    async def raise_second():
        await event.wait()
        return _TestError("second")

    with pytest.raises(_TestError, match="first"):
        await asyncio_compat.race(
            return_first(),  # The error always takes precedence.
            raise_first(),
            raise_second(),
        )


@pytest.mark.asyncio
async def test_race_raises_error_during_cancellation():
    async def return_normally():
        pass

    async def raise_if_cancelled():
        try:
            await asyncio.sleep(99)
        except asyncio.CancelledError:
            raise _TestError

    with pytest.raises(_TestError):
        await asyncio_compat.race(return_normally(), raise_if_cancelled())


@pytest.mark.asyncio
async def test_race_cancels_subtasks_if_cancelled():
    started = asyncio.Event()
    cancelled = False

    async def detect_cancelled():
        nonlocal cancelled
        try:
            started.set()
            await asyncio.sleep(99)
        except asyncio.CancelledError:
            cancelled = True
            raise

    async def do_race():
        await asyncio_compat.race(detect_cancelled())

    task = asyncio.create_task(do_race())
    await started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert cancelled
