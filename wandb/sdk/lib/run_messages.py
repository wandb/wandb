"""Echoing messages from wandb-core to the terminal."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from wandb.errors import term
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.interface import InterfaceBase
from wandb.sdk.lib import asyncio_compat, asyncio_manager, ratelimit

_logger = logging.getLogger(__name__)


class RunMessages:
    """Prints run messages from wandb-core.

    Messages are scoped to a run. In the future, we may want to switch to
    connection-level messages to allow `ServiceApi` operations to print
    and replace this by a new ServiceMessages class.
    """

    def __init__(
        self,
        asyncer: asyncio_manager.AsyncioManager,
        interface: InterfaceBase,
    ) -> None:
        self._asyncer = asyncer

        async def async_init() -> _RunMessagesImpl:
            return _RunMessagesImpl(interface)

        self._impl = asyncer.run(async_init)

    def start(self) -> None:
        """Start waiting for and printing generated messages."""
        self._asyncer.run_soon(
            self._impl.loop,
            daemon=True,
            name="RunMessages.loop",
        )

    def stop(self, *, timeout: float) -> None:
        """Stop the message loop after the run has exited.

        This should be called after wandb-core responds to the Exit record,
        after which it won't output more messages.

        Args:
            timeout: How long to wait, in seconds, before giving up.
                A warning is printed on timeout; some messages may get
                asynchronously printed in the future.
        """
        with contextlib.suppress(asyncio_manager.AlreadyJoinedError):
            self._asyncer.run(lambda: self._impl.stop(timeout=timeout))


class _RunMessagesImpl:
    def __init__(self, interface: InterfaceBase) -> None:
        self._interface = interface

        self._force_stop_event = asyncio.Event()  # timeout during stop()
        self._done_event = asyncio.Event()  # loop() done

    async def stop(self, *, timeout: float) -> None:
        """Stop the message loop after the run has exited.

        Assumes that `loop` has been or will be called.

        Args:
            timeout: How long to wait, in seconds, before giving up.
                On timeout, some messages may be missed or may print
                asynchronously.
        """
        # Since the run has exited, the loop will receive an empty response
        # from wandb-core and exit automatically.
        #
        # In case of a bug, we force-stop the loop after a timeout.
        try:
            await asyncio.wait_for(self._done_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            _logger.exception("Timed out waiting for messages.")
            self._force_stop_event.set()

    async def loop(self) -> None:
        """Print messages until forced to stop or the run exits."""
        try:
            await asyncio_compat.race(
                self._print_all(),
                self._force_stop_event.wait(),
            )

        finally:
            self._done_event.set()

    async def _print_all(self) -> None:
        """Print all of a run's messages until it exits."""
        # Rate limit to avoid busy-looping in case of a bug.
        # We won't need to print more than once every 100ms.
        rate_limit = ratelimit.Cooldown(0.1)
        while True:
            await rate_limit.wait()

            request = pb.Record(
                request=pb.Request(
                    internal_messages=pb.InternalMessagesRequest(wait=True),
                )
            )

            handle = await self._interface.deliver_async(request)
            result = await handle.wait_async(timeout=None)
            warnings = result.response.internal_messages_response.messages.warning

            # Since wait=True, no messages means the run exited.
            if not warnings:
                return

            for msg in warnings:
                term.termwarn(msg)
