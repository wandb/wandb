"""Stopping a run if requested by wandb-core.

A run can be stopped manually through the UI or automatically after
a fatal upload error (if configured). "Stopping" a run means killing
its script.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable

from wandb.agents import pyagent
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.interface import InterfaceBase
from wandb.sdk.lib import asyncio_compat, asyncio_manager

# Patched in tests.
_NOW = time.monotonic
_SLEEP = asyncio.sleep
_POLL_INTERVAL = 15


class RunStopChecker:
    """Kills the script if requested by wandb-core."""

    def __init__(
        self,
        asyncer: asyncio_manager.AsyncioManager,
        interface: InterfaceBase,
        stop_fn: Callable[[], None],
        *,
        poll_interval: float = _POLL_INTERVAL,
    ) -> None:
        self._asyncer = asyncer

        async def async_init() -> _RunStopCheckerImpl:
            return _RunStopCheckerImpl(
                interface,
                stop_fn,
                poll_interval=poll_interval,
            )

        self._impl = asyncer.run(async_init)

    def start(self) -> None:
        """Start checking for whether the run is stopped."""
        self._asyncer.run_soon(
            self._impl.loop,
            daemon=True,
            name="RunStopChecker.loop",
        )

    def stop_soon(self) -> None:
        """Stop the polling loop.

        This is best-effort. It is still possible for the status checker to
        kill the script for a short time after this function returns.
        """
        with contextlib.suppress(asyncio_manager.AlreadyJoinedError):
            self._asyncer.run(lambda: self._impl.stop_soon())


class _RunStopCheckerImpl:
    def __init__(
        self,
        interface: InterfaceBase,
        stop_fn: Callable[[], None],
        *,
        poll_interval: float,
    ) -> None:
        self._interface = interface
        self._stop_fn = stop_fn
        self._poll_interval = poll_interval
        self._stop_event = asyncio.Event()  # stop requested

    async def stop_soon(self) -> None:
        """Stop looping."""
        self._stop_event.set()

    async def loop(self) -> None:
        """Check the run's stop status until we are done."""
        while not self._stop_event.is_set():
            start_time = _NOW()
            should_stop = await self._check_should_stop()
            end_time = _NOW()

            # Only stop once.
            if should_stop:
                self._stop_fn()
                return

            remaining = self._poll_interval - (end_time - start_time)
            if remaining > 0:
                await asyncio_compat.race(
                    self._stop_event.wait(),  # wake up if stopping
                    _SLEEP(remaining),
                )

    async def _check_should_stop(self) -> bool:
        """Check whether the run should stop."""
        # TODO: Remove the pyagent.is_running() check if safe to do so.
        # See WB-3606.
        if pyagent.is_running():
            return False

        request = pb.Record(
            request=pb.Request(
                stop_status=pb.StopStatusRequest(),
            ),
        )

        handle = await self._interface.deliver_async(request)
        result = await handle.wait_async(timeout=None)
        return result.response.stop_status_response.run_should_stop
