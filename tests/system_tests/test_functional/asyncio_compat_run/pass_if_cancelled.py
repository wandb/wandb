from __future__ import annotations

import asyncio
import sys
import threading
import time

from wandb.sdk.lib import asyncio_compat

_got_cancelled_lock = threading.Lock()
_got_cancelled = False


async def pass_if_cancelled() -> None:
    global _got_cancelled

    try:
        print("TEST READY", flush=True)
        print(f"Ready at {time.monotonic()}", file=sys.stderr)
        await asyncio.sleep(5)

    except asyncio.CancelledError:
        # The test sends a SIGINT to the process, which we expect
        # asyncio_compat.run() to turn into task cancellation.
        with _got_cancelled_lock:
            _got_cancelled = True
        raise


if __name__ == "__main__":
    try:
        asyncio_compat.run(pass_if_cancelled)
    except KeyboardInterrupt:
        with _got_cancelled_lock:
            cancelled = _got_cancelled

        if cancelled:
            print(
                f"PASS: Cancelled by KeyboardInterrupt ({time.monotonic()})",
                file=sys.stderr,
            )
            sys.exit(0)
        else:
            print(
                f"FAIL: Interrupted but not cancelled ({time.monotonic()})",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(
            f"FAIL: Not interrupted by parent ({time.monotonic()})",
            file=sys.stderr,
        )
        sys.exit(1)
