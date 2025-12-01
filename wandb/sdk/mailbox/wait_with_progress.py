from __future__ import annotations

import time
from typing import Any, Callable, Coroutine, List, TypeVar, cast

from wandb.sdk.lib import asyncio_compat

from .mailbox_handle import MailboxHandle

_T = TypeVar("_T")


def wait_with_progress(
    handle: MailboxHandle[_T],
    *,
    timeout: float | None,
    display_progress: Callable[[], Coroutine[Any, Any, None]],
) -> _T:
    """Wait for a handle, possibly displaying progress to the user.

    Equivalent to passing a single handle to `wait_all_with_progress`.
    """
    return wait_all_with_progress(
        [handle],
        timeout=timeout,
        display_progress=display_progress,
    )[0]


def wait_all_with_progress(
    handle_list: list[MailboxHandle[_T]],
    *,
    timeout: float | None,
    display_progress: Callable[[], Coroutine[Any, Any, None]],
) -> list[_T]:
    """Wait for multiple handles, possibly displaying progress to the user.

    Args:
        handle_list: The handles to wait for.
        timeout: A number of seconds after which to raise a TimeoutError,
            or None if this should never timeout.
        display_progress: An asyncio function that displays progress to
            the user. This function runs using the handles' AsyncioManager.

    Returns:
        A list where the Nth item is the Nth handle's result.

    Raises:
        ValueError: If the handles live in different asyncio threads.
        TimeoutError: If the overall timeout expires.
        HandleAbandonedError: If any handle becomes abandoned.
        Exception: Any exception from the display function is propagated.
    """
    if not handle_list:
        return []

    asyncer = handle_list[0].asyncer
    for handle in handle_list:
        if handle.asyncer is not asyncer:
            raise ValueError("Handles have different AsyncioManagers.")

    start_time = time.monotonic()

    async def progress_loop_with_timeout() -> list[_T]:
        async with asyncio_compat.cancel_on_exit(display_progress()):
            if timeout is not None:
                elapsed_time = time.monotonic() - start_time
                remaining_timeout = timeout - elapsed_time
            else:
                remaining_timeout = None

            return await _wait_handles_async(
                handle_list,
                timeout=remaining_timeout,
            )

    return asyncer.run(progress_loop_with_timeout)


async def _wait_handles_async(
    handle_list: list[MailboxHandle[_T]],
    *,
    timeout: float | None,
) -> list[_T]:
    """Asynchronously wait for multiple mailbox handles.

    Just like _wait_handles.
    """
    results: list[_T | None] = [None for _ in handle_list]

    async def wait_single(index: int) -> None:
        handle = handle_list[index]
        results[index] = await handle.wait_async(timeout=timeout)

    async with asyncio_compat.open_task_group() as task_group:
        for index in range(len(handle_list)):
            task_group.start_soon(wait_single(index))

    # NOTE: `list` is not subscriptable until Python 3.10, so we use List.
    return cast(List[_T], results)
