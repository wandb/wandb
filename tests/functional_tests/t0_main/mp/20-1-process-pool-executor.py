#!/usr/bin/env python
"""Simple example of using ProcessPoolExecutor with service.
    This example is base on issue https://wandb.atlassian.net/browse/WB-8733
"""

from concurrent.futures import ProcessPoolExecutor

import wandb
import yea


def worker(log, info):
    log(info)
    return info


def main():
    wandb.require("service")
    with wandb.init() as run:
        with ProcessPoolExecutor() as executor:
            # log handler
            for i in range(3):
                future = executor.submit(worker, run.log, {"a": i})
                print(future.result())


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
