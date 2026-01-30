from __future__ import annotations

import asyncio
import logging
import math
from typing import Awaitable, Callable

from typing_extensions import override

from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager

from .mailbox_handle import HandleAbandonedError, MailboxHandle

_logger = logging.getLogger(__name__)


class MailboxResponseHandle(MailboxHandle[spb.ServerResponse]):
    """A general handle for any ServerResponse."""

    def __init__(
        self,
        address: str,
        *,
        asyncer: asyncio_manager.AsyncioManager,
        cancel: Callable[[str], Awaitable[None]],
    ) -> None:
        super().__init__(asyncer)

        self._address = address
        self._cancel_fn = cancel

        self._abandoned = False
        self._response: spb.ServerResponse | None = None

        # Initialized on first use in the asyncio thread.
        self._done_event: asyncio.Event | None = None

    async def deliver(self, response: spb.ServerResponse) -> None:
        if self._abandoned:
            return

        if self._response:
            raise ValueError(
                f"A response has already been delivered to {self._address}."
            )

        self._response = response

        if not self._done_event:
            self._done_event = asyncio.Event()
        self._done_event.set()

    @override
    def cancel(self) -> None:
        # Cancel on a best-effort basis and ignore exceptions.
        async def impl() -> None:
            try:
                await self._cancel_fn(self._address)
            except Exception:
                _logger.exception("Failed to cancel request %r", self._address)

        try:
            self.abandon()
            self.asyncer.run_soon(impl)
        except Exception:
            _logger.exception(
                "Failed to abandon and cancel request %r",
                self._address,
            )

    def abandon(self) -> None:
        """Indicate the handle will not receive a response.

        This causes any code blocked on `wait_or` or `wait_async` to raise
        a `HandleAbandonedError` after a short time.
        """

        async def impl() -> None:
            self._abandoned = True

            if not self._done_event:
                self._done_event = asyncio.Event()
            self._done_event.set()

        self.asyncer.run_soon(impl)

    @override
    def wait_or(self, *, timeout: float | None) -> spb.ServerResponse:
        return self.asyncer.run(lambda: self.wait_async(timeout=timeout))

    @override
    async def wait_async(self, *, timeout: float | None) -> spb.ServerResponse:
        if timeout is not None and not math.isfinite(timeout):
            raise ValueError("Timeout must be finite or None.")

        if not self._done_event:
            self._done_event = asyncio.Event()

        try:
            await asyncio.wait_for(self._done_event.wait(), timeout=timeout)

        except (asyncio.TimeoutError, TimeoutError) as e:
            if self._response:
                return self._response
            elif self._abandoned:
                raise HandleAbandonedError()
            else:
                self.cancel()
                raise TimeoutError(
                    f"Timed out waiting for response on {self._address}"
                ) from e

        except:
            self.cancel()
            raise

        else:
            if self._response:
                return self._response

            assert self._abandoned
            raise HandleAbandonedError()
