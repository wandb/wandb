"""_startup_debug.

Temporary helper to debug issues with wandb service startup
"""

import os
import time


def is_enabled() -> bool:
    # This is very temporary to help diagnose problems seen by some
    # customers which we are having trouble reproducing. It should be
    # replaced by something more permanent in the future when we have
    # proper logging for wandb-service
    if os.environ.get("_WANDB_STARTUP_DEBUG"):
        return True
    return False


def print_message(message: str) -> None:
    time_now = time.time()
    print("WANDB_STARTUP_DEBUG", time_now, message)  # noqa: T201
