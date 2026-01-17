"""Exits with code 0 if callbacks can be unregistered."""

from __future__ import annotations

import io
import sys

from wandb.sdk.lib import console_capture

received_by_hooks = io.StringIO()


def _stdout_hook1(data: str | bytes, written: int, /):
    received_by_hooks.write("[hook1]" + str(data[:written]))


def _stdout_hook2(data: str | bytes, written: int, /):
    received_by_hooks.write("[hook2]" + str(data[:written]))


if __name__ == "__main__":
    undo_stdout_hook1 = console_capture.capture_stdout(_stdout_hook1)
    undo_stdout_hook2 = console_capture.capture_stdout(_stdout_hook2)

    print("Line 1.")
    undo_stdout_hook1()
    print("Line 2.")
    undo_stdout_hook2()
    print("Line 3 (not received.)")

    received = received_by_hooks.getvalue()
    if received != (
        "[hook1]Line 1."  # (line-break for readability)
        "[hook2]Line 1."
        "[hook1]\n"  # NOTE: print() makes two write() calls!
        "[hook2]\n"
        "[hook2]Line 2."
        "[hook2]\n"
    ):
        print(f"Wrong data: {received!r}", file=sys.stderr)
        sys.exit(1)
