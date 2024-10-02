#!/usr/bin/env python
import os
import time

import yea

import wandb


def main():
    run = wandb.init()
    history = 200
    for i in range(history):
        print(i)
        run.log(dict(num=i))
        time.sleep(0.1)
    print("done")
    run.finish()

    should_retry = os.environ.get("SHOULD_RETRY")
    message = "requests_with_retry encountered retryable exception"

    with open(run.settings.log_internal) as f:
        internal_log = f.read()
        if should_retry == "true":
            assert message in internal_log
        else:
            assert message not in internal_log


if __name__ == "__main__":
    yea.setup()
    main()
