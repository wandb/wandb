"""Starts a W&B run and exits with code 1 if it's not interrupted."""

from __future__ import annotations

import sys
import time

import wandb
import wandb.sdk.wandb_run

if __name__ == "__main__":
    # The stop status is delivered via a FileStream response.
    settings = wandb.Settings(x_file_stream_transmit_interval=0.1)
    start_time: float | None = None

    # Use a faster polling interval to speed up the test.
    wandb.sdk.wandb_run._STOP_POLLING_INTERVAL = 0.1

    try:
        with wandb.init(settings=settings):
            start_time = time.monotonic()
            time.sleep(30)
    except KeyboardInterrupt:
        # Something like _thread.interrupt_main() would raise a
        # KeyboardInterrupt exception at the end of the sleep, instead of
        # interrupting the sleep.
        if start_time is not None and time.monotonic() - start_time >= 29:
            print("FAIL: Got KeyboardInterrupt too late!", file=sys.stderr)
            sys.exit(1)

        print("PASS: KeyboardInterrupt detected!", file=sys.stderr)
        sys.exit(0)

    print("FAIL: No KeyboardInterrupt detected!", file=sys.stderr)
    sys.exit(1)
