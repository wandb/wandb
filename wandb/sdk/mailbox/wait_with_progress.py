from __future__ import annotations

import time
from typing import Any, Callable, Coroutine

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib import asyncio_compat

from . import handles


def wait_with_progress(
    handle: handles.MailboxHandle,
    *,
    timeout: float | None,
    progress_after: float,
    display_progress: Callable[[], Coroutine[Any, Any, None]],
) -> pb.Result:
    """Wait for a handle, possibly displaying progress to the user.

    Args:
        handle: The handle to wait for.
        timeout: A number of seconds after which to raise a TimeoutError,
            or None if this should never timeout.
        progress_after: A number of seconds after which to start the
            progress_loop callback. Starting the callback creates a thread
            and starts an asyncio loop, so we want to avoid doing it if
            the handle is resolved quickly.
        display_progress: An asyncio function that displays progress to
            the user. This function is executed on a new thread and cancelled
            if the timeout is exceeded.

    Returns:
        The result, if it is received before the timeout.

    Raises:
        TimeoutError: If the overall timeout expires.
        HandleAbandonedError: If the handle becomes abandoned.
        Exception: Any other exception from the progress_loop is propagated.
    """
    if timeout is not None and timeout <= progress_after:
        return handle.wait_or(timeout=timeout)

    start_time = time.monotonic()

    try:
        return handle.wait_or(timeout=progress_after)
    except TimeoutError:
        pass

    async def progress_loop_with_timeout() -> pb.Result:
        with asyncio_compat.cancel_on_exit(display_progress()):
            if timeout is not None:
                elapsed_time = time.monotonic() - start_time
                remaining_timeout = timeout - elapsed_time
            else:
                remaining_timeout = None

            return await handle.wait_async(timeout=remaining_timeout)

    return asyncio_compat.run(progress_loop_with_timeout)
