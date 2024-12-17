"""Starts a W&B run and exits with code 1 if it's not interrupted."""

import sys
import time

import wandb

if __name__ == "__main__":
    with wandb.init():
        try:
            start_time = time.monotonic()
            time.sleep(30)
        except KeyboardInterrupt:
            # Something like _thread.interrupt_main() would raise a
            # KeyboardInterrupt exception at the end of the sleep, instead of
            # interrupting the sleep.
            if time.monotonic() - start_time >= 29:
                print("FAIL: Got KeyboardInterrupt too late!", file=sys.stderr)
                sys.exit(1)

            print("PASS: KeyboardInterrupt detected!", file=sys.stderr)
            sys.exit(0)

    print("FAIL: No KeyboardInterrupt detected!", file=sys.stderr)
    sys.exit(1)
