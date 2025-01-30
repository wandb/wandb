import asyncio
import sys

from wandb.sdk.lib import asyncio_compat

_got_cancelled = False


async def pass_if_cancelled() -> None:
    global _got_cancelled

    try:
        print("TEST READY", flush=True)  # noqa: T201
        await asyncio.sleep(5)

    except asyncio.CancelledError:
        # The test sends a SIGINT to the process, which we expect
        # asyncio_compat.run() to turn into task cancellation.
        _got_cancelled = True


if __name__ == "__main__":
    try:
        asyncio_compat.run(pass_if_cancelled)
    except KeyboardInterrupt:
        if _got_cancelled:
            print(  # noqa: T201
                "PASS: Cancelled by KeyboardInterrupt!",
                file=sys.stderr,
            )
            sys.exit(0)
        else:
            print(  # noqa: T201
                "FAIL: Interrupted but not cancelled!",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(  # noqa: T201
            "FAIL: Not interrupted by parent.",
            file=sys.stderr,
        )
        sys.exit(1)
