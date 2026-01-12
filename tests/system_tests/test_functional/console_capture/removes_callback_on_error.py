"""Exits with code 0 if callbacks are removed after raising an exception."""

from __future__ import annotations

import sys

from wandb.sdk.lib import console_capture

num_calls = 0


def count_and_interrupt(*unused) -> None:
    global num_calls
    num_calls += 1

    raise KeyboardInterrupt


if __name__ == "__main__":
    console_capture.capture_stdout(count_and_interrupt)

    try:
        # print() makes a separate write() call for the implicit \n,
        # making the output a little less nice.
        sys.stdout.write("First call -- should count.\n")
    except KeyboardInterrupt:
        # The callback must not suppress BaseExceptions.
        print("Got KeyboardInterrupt!")
    else:
        print("FAIL: No KeyboardInterrupt")
        sys.exit(1)

    print("Second call -- should not invoke callback.")

    if num_calls == 1:
        print("PASS: Only 1 call.")
        sys.exit(0)
    else:
        print(f"FAIL: Got {num_calls} calls, but expected 1.")
        sys.exit(1)
