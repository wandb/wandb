"""Passes if Ctrl+C during join() makes run() raise RunCancelledError."""

import asyncio
import sys
import threading
import time

from wandb.sdk.lib import asyncio_manager

_task_started = threading.Event()
_got_cancelled = threading.Event()


async def _set_task_started_then_sleep() -> None:
    _task_started.set()
    await asyncio.sleep(5)


def _detect_cancelled_task(asyncer: asyncio_manager.AsyncioManager) -> None:
    try:
        asyncer.run(_set_task_started_then_sleep)
    except asyncio_manager.RunCancelledError:
        _got_cancelled.set()


if __name__ == "__main__":
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    cancellation_test_thread = threading.Thread(
        target=_detect_cancelled_task,
        args=(asyncer,),
    )
    cancellation_test_thread.start()
    _task_started.wait()

    try:
        print("TEST READY", flush=True)
        asyncer.join()
    except KeyboardInterrupt:
        print(
            f"Got KeyboardInterrupt ({time.monotonic()=}), suppressing",
            file=sys.stderr,
        )
    else:
        print(
            f"FAIL: Not interrupted by parent ({time.monotonic()=})",
            file=sys.stderr,
        )
        sys.exit(1)

    if _got_cancelled.wait(timeout=5):
        print(
            f"PASS: Callback got cancellation error ({time.monotonic()=})",
            file=sys.stderr,
        )
        sys.exit(0)
    else:
        print(
            f"FAIL: No cancellation error ({time.monotonic()=})",
            file=sys.stderr,
        )
        sys.exit(1)
