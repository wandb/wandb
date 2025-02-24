from __future__ import annotations

import asyncio
import math
import sys
import threading
from typing import TYPE_CHECKING

from wandb.proto import wandb_server_pb2 as spb

from .mailbox_handle import HandleAbandonedError, MailboxHandle

# Necessary to break an import loop.
if TYPE_CHECKING:
    from wandb.sdk.interface import interface

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


class MailboxResponseHandle(MailboxHandle[spb.ServerResponse]):
    """A general handle for any ServerResponse."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._lock = threading.Lock()
        self._event = threading.Event()

        self._abandoned = False
        self._response: spb.ServerResponse | None = None

        self._asyncio_events: dict[asyncio.Event, _AsyncioEvent] = dict()

    def deliver(self, response: spb.ServerResponse) -> None:
        """Deliver the response.

        This may only be called once. It is an error to respond to the same
        request more than once. It is a no-op if the handle has been abandoned.
        """
        with self._lock:
            if self._abandoned:
                return

            if self._response:
                raise ValueError(
                    f"A response has already been delivered to {self._address}."
                )

            self._response = response
            self._signal_done()

    @override
    def cancel(self, iface: interface.InterfaceBase) -> None:
        iface.publish_cancel(self._address)
        self.abandon()

    @override
    def abandon(self) -> None:
        with self._lock:
            self._abandoned = True
            self._signal_done()

    def _signal_done(self) -> None:
        """Indicate that the handle either got a response or became abandoned.

        The lock must be held.
        """
        # Unblock threads blocked on `wait_or`.
        self._event.set()

        # Unblock asyncio loops blocked on `wait_async`.
        for asyncio_event in self._asyncio_events.values():
            asyncio_event.set_threadsafe()
        self._asyncio_events.clear()

    @override
    def check(self) -> spb.ServerResponse | None:
        with self._lock:
            return self._response

    @override
    def wait_or(self, *, timeout: float | None) -> spb.ServerResponse:
        if timeout is not None and not math.isfinite(timeout):
            raise ValueError("Timeout must be finite or None.")

        if not self._event.wait(timeout=timeout):
            raise TimeoutError(
                f"Timed out waiting for response on {self._address}",
            )

        with self._lock:
            if self._response:
                return self._response

            assert self._abandoned
            raise HandleAbandonedError()

    @override
    async def wait_async(self, *, timeout: float | None) -> spb.ServerResponse:
        if timeout is not None and not math.isfinite(timeout):
            raise ValueError("Timeout must be finite or None.")

        evt = asyncio.Event()
        self._add_asyncio_event(asyncio.get_event_loop(), evt)

        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout)

        except (asyncio.TimeoutError, TimeoutError) as e:
            with self._lock:
                if self._response:
                    return self._response
                elif self._abandoned:
                    raise HandleAbandonedError()
                else:
                    raise TimeoutError(
                        f"Timed out waiting for response on {self._address}"
                    ) from e

        else:
            with self._lock:
                if self._response:
                    return self._response

                assert self._abandoned
                raise HandleAbandonedError()

        finally:
            self._forget_asyncio_event(evt)

    def _add_asyncio_event(
        self,
        loop: asyncio.AbstractEventLoop,
        event: asyncio.Event,
    ) -> None:
        """Add an event to signal when a response is received.

        If a response already exists, this notifies the event loop immediately.
        """
        asyncio_event = _AsyncioEvent(loop, event)

        with self._lock:
            if self._response or self._abandoned:
                asyncio_event.set_threadsafe()
            else:
                self._asyncio_events[event] = asyncio_event

    def _forget_asyncio_event(self, event: asyncio.Event) -> None:
        """Cancel signalling an event when a response is received."""
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
