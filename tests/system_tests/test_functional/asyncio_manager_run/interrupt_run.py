"""Tests that interrupting run() cancels its task, but not others."""

from __future__ import annotations

import asyncio
import sys

from wandb.sdk.lib import asyncio_manager

_queue: asyncio.Queue[str]


async def _init() -> None:
    global _queue
    _queue = asyncio.Queue()


async def _print_queue() -> None:
    while s := await _queue.get():
        print(s, flush=True)


async def _add_to_queue_then_sleep() -> None:
    await _queue.put("STARTED")

    try:
        await asyncio.sleep(9999)

    except asyncio.CancelledError:
        await _queue.put("CANCELLED")
        raise


if __name__ == "__main__":
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()
    asyncer.run(_init)
    asyncer.run_soon(_print_queue, daemon=True)

    try:
        asyncer.run(_add_to_queue_then_sleep)
    except KeyboardInterrupt:
        sys.stderr.write("Got first interrupt\n")
    else:
        sys.stderr.write("FAIL: Not interrupted\n")
        sys.exit(1)

    # _print_queue should not get cancelled by the above interrupt.
    sys.stdin.readline()
    asyncer.run(lambda: _queue.put("STILL GOOD"))
    asyncer.join()
