"""Exits with code 0 if no deadlock occurs, and hangs otherwise."""

from __future__ import annotations

import concurrent.futures
import sys

from wandb.sdk.lib import console_capture


def _info(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def _main() -> None:
    reset = console_capture.capture_stdout(_check_reentrant)
    _info("Testing _check_reentrant.")
    sys.stdout.write("_check_reentrant\n")
    _info("Success!")
    reset()

    reset = console_capture.capture_stdout(_check_block_on_other_thread)
    _info("Testing _check_block_on_other_thread.")
    sys.stdout.write("_check_block_on_other_thread\n")
    _info("Success!")
    reset()


def _check_reentrant(data: bytes | str, written: int) -> None:
    sys.stdout.write("This shouldn't deadlock or loop indefinitely.\n")


def _check_block_on_other_thread(data: bytes | str, written: int) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: sys.stdout.write("This shouldn't deadlock.\n"))
        future.result()


if __name__ == "__main__":
    _main()
