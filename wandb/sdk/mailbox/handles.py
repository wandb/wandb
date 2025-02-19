from __future__ import annotations

import asyncio
import math
import threading
from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb

# Necessary to break an import loop.
if TYPE_CHECKING:
    from wandb.sdk.interface import interface


class HandleAbandonedError(Exception):
    """The handle has no result and has been abandoned."""


class MailboxHandle:
    """A thread-safe handle that allows waiting for a response to a request."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._lock = threading.Lock()
        self._event = threading.Event()

        self._abandoned = False
        self._result: pb.Result | None = None

        self._asyncio_events: dict[asyncio.Event, _AsyncioEvent] = dict()

    def deliver(self, result: pb.Result) -> None:
        """Deliver the response.

        This may only be called once. It is an error to respond to the same
        request more than once. It is a no-op if the handle has been abandoned.
        """
        with self._lock:
            if self._abandoned:
                return

            if self._result:
                raise ValueError(
                    f"A response has already been delivered to {self._address}."
                )

            self._result = result
            self._signal_done()

    def cancel(self, iface: interface.InterfaceBase) -> None:
        """Cancel the handle, requesting any associated work to not complete.

        This automatically abandons the handle, as a response is no longer
        guaranteed.

        Args:
            interface: The interface on which to publish the cancel request.
        """
        iface.publish_cancel(self._address)
        self.abandon()

    def abandon(self) -> None:
        """Abandon the handle, indicating it will not receive a response."""
        with self._lock:
            self._abandoned = True
            self._signal_done()

    def _signal_done(self) -> None:
        """Indicate that the handle either got a result or became abandoned.

        The lock must be held.
        """
        # Unblock threads blocked on `wait_or`.
        self._event.set()

        # Unblock asyncio loops blocked on `wait_async`.
        for asyncio_event in self._asyncio_events.values():
            asyncio_event.set_threadsafe()
        self._asyncio_events.clear()

    def check(self) -> pb.Result | None:
        """Returns the result if it's ready."""
        with self._lock:
            return self._result

    def wait_or(self, *, timeout: float | None) -> pb.Result:
        """Wait for a response or a timeout.

        This is called `wait_or` because it replaces a method called `wait`
        with different semantics.

        Args:
            timeout: A finite number of seconds or None to never time out.
                If less than or equal to zero, times out immediately unless
                the result is available.

        Returns:
            The result if it arrives before the timeout or has already arrived.

        Raises:
            TimeoutError: If the timeout is reached.
            HandleAbandonedError: If the handle becomes abandoned.
        """
        if timeout is not None and not math.isfinite(timeout):
            raise ValueError("Timeout must be finite or None.")

        if not self._event.wait(timeout=timeout):
            raise TimeoutError(
                f"Timed out waiting for response on {self._address}",
            )

        with self._lock:
            if self._result:
                return self._result

            assert self._abandoned
            raise HandleAbandonedError()

    async def wait_async(self, *, timeout: float | None) -> pb.Result:
        """Wait for a response or timeout.

        This must run in an `asyncio` event loop.

        Args:
            timeout: A finite number of seconds or None to never time out.

        Returns:
            The result if it arrives before the timeout or has already arrived.

        Raises:
            TimeoutError: If the timeout is reached.
            HandleAbandonedError: If the handle becomes abandoned.
        """
        if timeout is not None and not math.isfinite(timeout):
            raise ValueError("Timeout must be finite or None.")

        evt = asyncio.Event()
        self._add_asyncio_event(asyncio.get_event_loop(), evt)

        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout)

        except (asyncio.TimeoutError, TimeoutError) as e:
            with self._lock:
                if self._result:
                    return self._result
                elif self._abandoned:
                    raise HandleAbandonedError()
                else:
                    raise TimeoutError(
                        f"Timed out waiting for response on {self._address}"
                    ) from e

        else:
            with self._lock:
                if self._result:
                    return self._result

                assert self._abandoned
                raise HandleAbandonedError()

        finally:
            self._forget_asyncio_event(evt)

    def _add_asyncio_event(
        self,
        loop: asyncio.AbstractEventLoop,
        event: asyncio.Event,
    ) -> None:
        """Add an event to signal when a result is received.

        If a result already exists, this notifies the event loop immediately.
        """
        asyncio_event = _AsyncioEvent(loop, event)

        with self._lock:
            if self._result or self._abandoned:
                asyncio_event.set_threadsafe()
            else:
                self._asyncio_events[event] = asyncio_event

    def _forget_asyncio_event(self, event: asyncio.Event) -> None:
        """Cancel signalling an event when a result is received."""
        with self._lock:
            self._asyncio_events.pop(event, None)


class _AsyncioEvent:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        event: asyncio.Event,
    ):
        self._loop = loop
        self._event = event

    def set_threadsafe(self) -> None:
        """Set the asyncio event in its own loop."""
        self._loop.call_soon_threadsafe(self._event.set)
