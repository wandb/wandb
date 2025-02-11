"""Functions for compatibility with asyncio."""

from __future__ import annotations

import asyncio
import concurrent
import concurrent.futures
import contextlib
import threading
from typing import Any, AsyncIterator, Callable, Coroutine, Iterator, TypeVar

_T = TypeVar("_T")


def run(fn: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
    """Run `fn` in an asyncio loop in a new thread.

    This must always be used instead of `asyncio.run` which fails if there is
    an active `asyncio` event loop in the current thread. Since `wandb` was not
    originally designed with `asyncio` in mind, using `asyncio.run` would break
    users who were calling `wandb` methods from an `asyncio` loop.

    Note that due to starting a new thread, this is slightly slow.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        runner = _Runner()
        future = executor.submit(runner.run, fn)

        try:
            return future.result()

        finally:
            runner.cancel()


class _RunnerCancelledError(Exception):
    """The `_Runner.run()` invocation was cancelled."""


class _Runner:
    """Runs an asyncio event loop allowing cancellation.

    This is like `asyncio.run()`, except it provides a `cancel()` method
    meant to be called in a `finally` block.

    Without this, it is impossible to make `asyncio.run()` stop if it runs
    in a non-main thread. In particular, a KeyboardInterrupt causes the
    ThreadPoolExecutor above to block until the asyncio thread completes,
    but there is no way to tell the asyncio thread to cancel its work.
    A second KeyboardInterrupt makes ThreadPoolExecutor give up while the
    asyncio thread still runs in the background, with terrible effects if it
    prints to the user's terminal.
    """

    def __init__(self) -> None:
        self._lock = threading.Condition()

        self._is_cancelled = False
        self._started = False
        self._done = False

        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancel_event: asyncio.Event | None = None

    def run(self, fn: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
        """Run a coroutine in asyncio, cancelling it on `cancel()`.

        Returns:
            The result of the coroutine returned by `fn`.

        Raises:
            _RunnerCancelledError: If `cancel()` is called.
        """
        return asyncio.run(self._run_or_cancel(fn))

    async def _run_or_cancel(
        self,
        fn: Callable[[], Coroutine[Any, Any, _T]],
    ) -> _T:
        with self._lock:
            if self._is_cancelled:
                raise _RunnerCancelledError()

            self._loop = asyncio.get_running_loop()
            self._cancel_event = asyncio.Event()
            self._started = True

        cancellation_task = asyncio.create_task(self._cancel_event.wait())
        fn_task = asyncio.create_task(fn())

        try:
            await asyncio.wait(
                [cancellation_task, fn_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if fn_task.done():
                return fn_task.result()
            else:
                raise _RunnerCancelledError()

        finally:
            cancellation_task.cancel()
            fn_task.cancel()

            with self._lock:
                self._done = True

    def cancel(self) -> None:
        """Cancel all asyncio work started by `run()`."""
        with self._lock:
            if self._is_cancelled:
                return
            self._is_cancelled = True

            if self._done or not self._started:
                # If the runner already finished, no need to cancel it.
                #
                # If the runner hasn't started the loop yet, then it will not
                # as we already set _is_cancelled.
                return

            assert self._loop
            assert self._cancel_event
            self._loop.call_soon_threadsafe(self._cancel_event.set)


class TaskGroup:
    """Object that `open_task_group()` yields."""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def start_soon(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule a task in the group.

        Args:
            coro: The return value of the `async` function defining the task.
        """
        self._tasks.append(asyncio.create_task(coro))

    async def _wait_all(self) -> None:
        """Block until all tasks complete.

        Raises:
            Exception: If one or more tasks raises an exception, one of these
                is raised arbitrarily.
        """
        done, _ = await asyncio.wait(
            self._tasks,
            # NOTE: Cancelling a task counts as a normal exit,
            #   not an exception.
            return_when=concurrent.futures.FIRST_EXCEPTION,
        )

        for task in done:
            try:
                if exc := task.exception():
                    raise exc
            except asyncio.CancelledError:
                pass

    def _cancel_all(self) -> None:
        """Cancel all tasks."""
        for task in self._tasks:
            # NOTE: It is safe to cancel tasks that have already completed.
            task.cancel()


@contextlib.asynccontextmanager
async def open_task_group() -> AsyncIterator[TaskGroup]:
    """Create a task group.

    `asyncio` gained task groups in Python 3.11.

    This is an async context manager, meant to be used with `async with`.
    On exit, it blocks until all subtasks complete. If any subtask fails, or if
    the current task is cancelled, it cancels all subtasks in the group and
    raises the subtask's exception. If multiple subtasks fail simultaneously,
    one of their exceptions is chosen arbitrarily.

    NOTE: Subtask exceptions do not propagate until the context manager exits.
    This means that the task group cannot cancel code running inside the
    `async with` block .
    """
    task_group = TaskGroup()

    try:
        yield task_group
        await task_group._wait_all()
    finally:
        task_group._cancel_all()


@contextlib.contextmanager
def cancel_on_exit(coro: Coroutine[Any, Any, Any]) -> Iterator[None]:
    """Schedule a task, cancelling it when exiting the context manager.

    If the given coroutine raises an exception, that exception is raised
    when exiting the context manager.
    """
    task = asyncio.create_task(coro)

    try:
        yield
    finally:
        if task.done() and (exception := task.exception()):
            raise exception

        task.cancel()
