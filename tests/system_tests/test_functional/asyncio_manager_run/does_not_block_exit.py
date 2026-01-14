"""Tests that the asyncio thread is daemon."""

import asyncio
import threading
import time

from wandb.sdk.lib import asyncio_manager


def _avoid_hanging_ci(asyncer: asyncio_manager.AsyncioManager) -> None:
    """Join the asyncio thread if the test takes too long."""

    def _join_manager():
        # If the test finishes successfully, Python kills the daemon while
        # it sleeps.
        time.sleep(5)
        asyncer.join()
        print("FAIL")

    threading.Thread(target=_join_manager, daemon=True).start()


if __name__ == "__main__":
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    _avoid_hanging_ci(asyncer)
    asyncer.run_soon(lambda: asyncio.sleep(9999), daemon=False)
