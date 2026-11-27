"""Child process for Unix socket temp-dir cleanup system tests."""

from __future__ import annotations

import signal
import sys

import wandb
from wandb.sdk import wandb_setup


def main() -> int:
    run = wandb.init(
        id="unix-socket-cleanup-child",
        mode="offline",
        tags=["unix-socket-cleanup"],
    )
    run.log({"step": 0})

    connection = wandb_setup.singleton()._connection
    if connection is None or connection._proc is None:
        print("ERROR missing service connection", flush=True)
        return 1

    core_pid = connection._proc._process.pid
    print(f"READY {core_pid}", flush=True)

    signal.pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())
