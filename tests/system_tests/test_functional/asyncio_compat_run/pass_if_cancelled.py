import asyncio
import sys
import threading
import time

from wandb.sdk.lib import asyncio_compat

_got_cancelled = threading.Event()


async def pass_if_cancelled() -> None:
    global _got_cancelled

    try:
        print(f"Ready at {time.monotonic()}", file=sys.stderr)
        print("TEST READY", flush=True)
        await asyncio.sleep(5)

        # If this happens, the CI machine is running too slowly.
        print(f"Finished sleeping at {time.monotonic()}", file=sys.stderr)

    except asyncio.CancelledError:
        # The test sends a SIGINT to the process, which we expect
        # asyncio_compat.run() to turn into task cancellation.
        print(f"CancelledError caught at {time.monotonic()}", file=sys.stderr)
        _got_cancelled.set()
        raise


if __name__ == "__main__":
    try:
        asyncio_compat.run(pass_if_cancelled)
    except KeyboardInterrupt:
        # If the interrupt is sent at an unlucky time, it is possible for
        # the thread started by run() to "leak" and continue running after
        # it returns. However, run() guarantees that that thread will
        # get a CancelledError if it successfully entered the asyncio loop.
        cancelled = _got_cancelled.wait(timeout=2)

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
