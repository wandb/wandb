"""Functions for compatibility with asyncio."""

from __future__ import annotations

import asyncio
import concurrent
import concurrent.futures
import contextlib
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

    def run_in_asyncio() -> _T:
        return asyncio.run(fn())

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_in_asyncio)
        return future.result()


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
    the current task is cancelled, all subtasks in the group are cancelled.
    """
    task_group = TaskGroup()

    try:
        yield task_group
        await task_group._wait_all()
    finally:
        task_group._cancel_all()


@contextlib.contextmanager
def cancel_on_exit(coro: Coroutine[Any, Any, Any]) -> Iterator[None]:
    """Schedule a task, cancelling it when exiting the context manager."""
    task = asyncio.create_task(coro)

    try:
        yield
    finally:
        task.cancel()
