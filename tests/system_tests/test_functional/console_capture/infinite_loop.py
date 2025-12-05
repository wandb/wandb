"""Fails if tasks started by console callbacks invoke more callbacks."""

from __future__ import annotations

import asyncio
import sys

from wandb.sdk.lib import asyncio_manager, console_capture


def _info(msg: str) -> None:
    sys.stderr.write(msg + "\n")


class _Tester:
    def __init__(self) -> None:
        self._asyncer = asyncio_manager.AsyncioManager()
        self._scheduled_message: asyncio.Event
        self._outside_of_callback: asyncio.Event
        self._callback_count = 0

    def run(self) -> None:
        self._asyncer.start()
        self._asyncer.run(self._run)
        self._asyncer.join()

    async def _run(self) -> None:
        self._scheduled_message = asyncio.Event()
        self._outside_of_callback = asyncio.Event()

        # The callback should be invoked before write() returns.
        # This is a precondition for the test to make sense.
        sys.stdout.write("Initial message.\n")
        if self._callback_count != 1:
            _info(f"FAIL: Precondition not satisfied ({self._callback_count=})")
            sys.exit(1)

        # Allow the scheduled task to print. Its message should not be captured
        # even though we're not inside the write() anymore.
        self._outside_of_callback.set()
        await self._scheduled_message.wait()
        if self._callback_count != 1:
            _info(f"FAIL: Unexpected callback count ({self._callback_count=})")
            sys.exit(1)

    def callback(self, data: bytes | str, written: int) -> None:
        _ = data
        _ = written

        self._callback_count += 1
        self._asyncer.run_soon(self._print_more_later)

    async def _print_more_later(self) -> None:
        await self._outside_of_callback.wait()
        sys.stdout.write("Scheduled message.\n")
        self._scheduled_message.set()


def main() -> None:
    tester = _Tester()

    reset = console_capture.capture_stdout(tester.callback)
    tester.run()
    reset()


if __name__ == "__main__":
    main()
