"""Echoing messages from wandb-core to the terminal."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from wandb.errors import term
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.interface import InterfaceBase
from wandb.sdk.lib import asyncio_compat, asyncio_manager

# Patched in tests.
_NOW = time.monotonic
_SLEEP = asyncio.sleep


_logger = logging.getLogger(__name__)


class RunMessages:
    """Polls and prints run messages from wandb-core.

    Messages are scoped to a run. In the future, we may want to switch to
    connection-level messages to allow `ServiceApi` operations to print
    and replace this by a new ServiceMessages class.
    """

    def __init__(
        self,
        asyncer: asyncio_manager.AsyncioManager,
        interface: InterfaceBase,
        *,
        poll_interval: float = 10,
    ) -> None:
        self._asyncer = asyncer

        async def async_init() -> _RunMessagesImpl:
            return _RunMessagesImpl(interface, poll_interval=poll_interval)

        self._impl = asyncer.run(async_init)

    def start(self) -> None:
        """Start polling for and printing generated messages."""
        self._asyncer.run_soon(
            self._impl.loop,
            daemon=True,
            name="RunMessages.loop",
        )

    def stop(self, *, timeout: float) -> None:
        """Stop the polling loop and print any final messages.

        Args:
            timeout: How long to wait, in seconds, before giving up.
                A warning is printed on timeout; some messages may get
                asynchronously printed in the future.
        """
        with contextlib.suppress(asyncio_manager.AlreadyJoinedError):
            self._asyncer.run(lambda: self._impl.stop(timeout=timeout))


class _RunMessagesImpl:
    def __init__(
        self,
        interface: InterfaceBase,
        *,
        poll_interval: float,
    ) -> None:
        self._interface = interface
        self._poll_interval = poll_interval

        self._stop_event = asyncio.Event()  # stop requested
        self._done_event = asyncio.Event()  # loop() done

    async def stop(self, *, timeout: float) -> None:
        """Stop looping and print any final messages.

        Assumes that `loop` has been or will be called.

        Args:
            timeout: How long to wait, in seconds, before giving up.
                On timeout, some messages may be missed or may print
                asynchronously.
        """
        timeout_at = time.monotonic() + timeout

        self._stop_event.set()
        try:
            await asyncio.wait_for(self._done_event.wait(), timeout)
            await self._poll_and_print(timeout=timeout_at - time.monotonic())

        # NOTE: asyncio.TimeoutError is different from TimeoutError
        #   until Python 3.11.
        except (asyncio.TimeoutError, TimeoutError):
            _logger.exception("Timed out waiting for messages.")

    async def loop(self) -> None:
        """Print messages until asked to stop."""
        try:
            while not self._stop_event.is_set():
                start_time = _NOW()
                await self._poll_and_print(timeout=None)
                end_time = _NOW()

                remaining = self._poll_interval - (end_time - start_time)
                if remaining > 0:
                    await asyncio_compat.race(
                        self._stop_event.wait(),  # wake up if stopping
                        _SLEEP(remaining),
                    )
        finally:
            self._done_event.set()

    async def _poll_and_print(self, *, timeout: float | None) -> None:
        """Fetch and print messages.

        Args:
            timeout: How long to wait for wandb-core to respond.

        Raises:
            TimeoutError: if timeout was specified and was exceeded.
                If a timeout occurs, some messages may be lost.
        """
        request = pb.Record(
            request=pb.Request(
                internal_messages=pb.InternalMessagesRequest(),
            )
        )

        handle = await self._interface.deliver_async(request)
        result = await handle.wait_async(timeout=timeout)

        warnings = result.response.internal_messages_response.messages.warning
        for msg in warnings:
            term.termwarn(msg)
