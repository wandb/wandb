"""Implements an asyncio thread suitable for internal wandb use."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import logging
import threading
from typing import Any, Callable, Coroutine, TypeVar

from . import asyncio_compat

_T = TypeVar("_T")

_logger = logging.getLogger(__name__)


class RunCancelledError(Exception):
    """A function passed to AsyncioManager.run() was cancelled."""


class AlreadyJoinedError(Exception):
    """AsyncioManager.run() used after join()."""


class AsyncioManager:
    """Manages a thread running an asyncio loop.

    The thread must be started using start() and should be joined using
    join(). The thread is a daemon thread, so if join() is not invoked,
    the asyncio work could end abruptly when all non-daemon threads exit.

    The run() method allows invoking an async function in the asyncio thread
    and waiting until it completes. The run_soon() method allows running
    an async function without waiting for it.

    Note that although tempting, it is **not** possible to write a safe
    run_in_loop() method that chooses whether to use run() or execute a function
    directly based on whether it's called from the asyncio thread: Suppose a
    function bad() holds a threading.Lock while using run_in_loop() and an
    asyncio task calling bad() is scheduled. If bad() is then invoked in a
    different thread that reaches run_in_loop(), the aforementioned asyncio task
    will deadlock. It is unreasonable to require that run_in_loop() never be
    called while holding a lock (which would apply to the callers of its
    callers, and so on), so it cannot safely exist.
    """

    def __init__(self) -> None:
        self._runner = asyncio_compat.CancellableRunner()
        self._thread = threading.Thread(
            target=self._main,
            name="wandb-AsyncioManager-main",
            daemon=True,
        )
        self._lock = threading.Lock()

        self._ready_event = threading.Event()
        """Whether asyncio primitives have been initialized."""

        self._joined = False
        """Whether join() has been called. Guarded by _lock."""

        self._loop: asyncio.AbstractEventLoop
        """A handle for interacting with the asyncio event loop."""

        self._done_event: asyncio.Event
        """Indicates to the asyncio loop that join() was called."""

        self._remaining_tasks = 0
        """The number of tasks remaining. Guarded by _lock."""

        self._task_finished_cond: asyncio.Condition
        """Signalled when _remaining_tasks is decremented."""

    def start(self) -> None:
        """Start the asyncio thread."""
        self._thread.start()

    def join(self) -> None:
        """Stop accepting new asyncio tasks and wait for the remaining ones."""
        try:
            with self._lock:
                # If join() was already called, block until the thread completes
                # and then return.
                if self._joined:
                    self._thread.join()
                    return

                self._joined = True

            # Wait until _loop and _done_event are initialized.
            self._ready_event.wait()

            # Set the done event. The main function will exit once all
            # tasks complete.
            self._loop.call_soon_threadsafe(self._done_event.set)

            self._thread.join()

        finally:
            # Any of the above may get interrupted by Ctrl+C, in which case we
            # should cancel all tasks, since join() can only be called once.
            # This only matters if the KeyboardInterrupt is suppressed.
            self._runner.cancel()

    def run(self, fn: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
        """Run an async function to completion.

        The function is called in the asyncio thread. Blocks until start()
        is called. This raises an error if called inside an async function,
        and as a consequence, the caller may also not be called inside an
        async function.

        Args:
            fn: The function to run.

        Returns:
            The return value of fn.

        Raises:
            Exception: Any exception raised by fn.
            RunCancelledError: If fn is cancelled, particularly when join()
                is interrupted by Ctrl+C or if it otherwise cancels itself.
            AlreadyJoinedError: If join() was already called.
            ValueError: If called inside an async function.
        """
        self._ready_event.wait()

        if threading.current_thread().ident == self._thread.ident:
            raise ValueError("Cannot use run() inside async loop.")

        future = self._schedule(fn, daemon=False)

        try:
            return future.result()

        except concurrent.futures.CancelledError:
            raise RunCancelledError from None

        except KeyboardInterrupt:
            # If we're interrupted here, we only cancel this task rather than
            # cancelling all tasks like in join(). This only matters if the
            # interrupt is then suppressed (or delayed) in which case we
            # should let other tasks progress.
            future.cancel()
            raise

    def run_soon(
        self,
        fn: Callable[[], Coroutine[Any, Any, None]],
        *,
        daemon: bool = False,
        name: str | None = None,
    ) -> None:
        """Run an async function without waiting for it to complete.

        The function is called in the asyncio thread. Note that since that's
        a daemon thread, it will not get joined when the main thread exits,
        so fn can stop abruptly.

        Unlike run(), it is OK to call this inside an async function.

        Blocks until start() is called.

        Args:
            fn: The function to run.
            daemon: If true, join() will cancel fn after all non-daemon
                tasks complete. By default, join() blocks until fn
                completes.
            name: An optional name to give to long-running tasks which can
                appear in error traces and be useful to debugging.

        Raises:
            AlreadyJoinedError: If join() was already called.
        """

        # Wrap exceptions so that they're not printed to console.
        async def fn_wrap_exceptions() -> None:
            try:
                await fn()
            except Exception:
                _logger.exception("Uncaught exception in run_soon callback.")

        _ = self._schedule(fn_wrap_exceptions, daemon=daemon, name=name)

    def _schedule(
        self,
        fn: Callable[[], Coroutine[Any, Any, _T]],
        daemon: bool,
        name: str | None = None,
    ) -> concurrent.futures.Future[_T]:
        # Wait for _loop to be initialized.
        self._ready_event.wait()

        with self._lock:
            if self._joined:
                raise AlreadyJoinedError

            if not daemon:
                self._remaining_tasks += 1

        return asyncio.run_coroutine_threadsafe(
            self._wrap(fn, daemon=daemon, name=name),
            self._loop,
        )

    async def _wrap(
        self,
        fn: Callable[[], Coroutine[Any, Any, _T]],
        daemon: bool,
        name: str | None,
    ) -> _T:
        """Run fn to completion and possibly decrement _remaining tasks."""
        try:
            if name and (task := asyncio.current_task()):
                task.set_name(name)

            return await fn()
        finally:
            if not daemon:
                async with self._task_finished_cond:
                    with self._lock:
                        self._remaining_tasks -= 1
                    self._task_finished_cond.notify_all()

    def _main(self) -> None:
        """Run the asyncio loop until join() is called and all tasks finish."""
        # A cancellation error is expected if join() is interrupted.
        #
        # Were it not suppressed, its stacktrace would get printed.
        with contextlib.suppress(asyncio_compat.RunnerCancelledError):
            self._runner.run(self._main_async)

    async def _main_async(self) -> None:
        """Wait until join() is called and all tasks finish."""
        self._loop = asyncio.get_running_loop()
        self._done_event = asyncio.Event()
        self._task_finished_cond = asyncio.Condition()

        self._ready_event.set()

        # Wait until done.
        await self._done_event.wait()

        # Wait for all tasks to complete.
        #
        # Once we exit, asyncio will cancel any leftover tasks.
        async with self._task_finished_cond:
            await self._task_finished_cond.wait_for(
                lambda: self._remaining_tasks <= 0,
            )
