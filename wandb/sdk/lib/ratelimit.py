"""A small asyncio rate limiter."""

import asyncio

from wandb.sdk.lib import asyncio_compat


class Cooldown:
    """A very simple rate limiter for asyncio loops.

    Implemented by sleeping until the next unblock time.

    Use the `looptime` package to test code that uses this.
    """

    def __init__(self, cooldown: float, /) -> None:
        """Initialize the rate limiter.

        The first `wait` will return immediately.

        Args:
            cooldown: The number of seconds that must pass between consecutive
                events. The reciprocal of the frequency (events per second).
        """
        self._cooldown = cooldown

        # Allow the next event immediately.
        self._unblock_at = asyncio_compat.now()

    async def wait(self) -> None:
        """Wait for the cooldown, then reset it.

        This can be called from multiple tasks at the same time,
        in which case an arbitrary task will win, and the others will
        continue waiting for the new cooldown.

        Does not affect the cooldown if cancelled.
        """
        now = asyncio_compat.now()
        remaining = self._unblock_at - now

        if remaining <= 0:
            self._unblock_at = now + self._cooldown
            return

        # Set the unblock time for the next `wait()` before sleeping,
        # in case `wait()` is called again concurrently.
        self._unblock_at += self._cooldown
        await asyncio.sleep(remaining)
