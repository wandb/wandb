#!/usr/bin/env python
import shutil
import time
from typing import Any, Dict

import sentry_sdk


def main():
    third_party_sentry_events = []

    # store events in a list instead of sending them to Sentry
    def capture_event(event: Dict[str, Any]) -> None:
        if "exception" in event:
            third_party_sentry_events.append(event)

    # this should not interfere with our Sentry integration
    sentry_sdk.init(transport=capture_event)

    import wandb
    import wandb.env

    # assert that importing wandb does not set Sentry's global hub/client
    assert sentry_sdk.Hub.current.client.dsn != wandb._sentry.dsn
    # but an internal Sentry client for wandb is created ok if WANDB_ERROR_REPORTING != False
    if wandb.env.error_reporting_enabled():
        assert isinstance(wandb._sentry.hub, sentry_sdk.hub.Hub)

    run = wandb.init()

    # raise two exceptions and capture them with the third-party sentry client
    for i in range(2):
        try:
            print(
                f"Raising exception #{i + 1} to be captured by third-party sentry client"
            )
            raise ValueError("Catch me if you can!")
        except ValueError:
            sentry_sdk.capture_exception()

    num_third_party_sentry_events = len(third_party_sentry_events)
    run.log({"num_third_party_sentry_events": num_third_party_sentry_events})

    time.sleep(2)

    # Triggers a FileNotFoundError from the internal process
    # because the internal process reads/writes to the current run directory.
    shutil.rmtree(run.dir)
    try:
        run.log({"data": 5})
    except FileNotFoundError:
        pass

    # no new events should be captured
    assert num_third_party_sentry_events == len(third_party_sentry_events)


if __name__ == "__main__":
    main()
