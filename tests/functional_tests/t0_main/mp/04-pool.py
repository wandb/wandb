#!/usr/bin/env python
"""pool with finish."""

import multiprocessing as mp
import sys

import time
import wandb
import yea


def do_run(num):
    run = wandb.init()
    run.config.id = num
    run.log(dict(s=num))
    print("hello1:", num, file=sys.stderr)
    print("hello2:", num, file=sys.stderr)
    # time.sleep(20)
    run.finish()
    return num


def main():
    wandb.require("service")
    wandb.setup()
    print("hello0000", file=sys.stderr)
    print("hello0001", file=sys.stderr)
    num_proc = 4
    pool = mp.Pool(processes=num_proc)
    result = pool.map_async(do_run, range(num_proc))

    data = result.get(60)
    print(f"DEBUG: {data}", file=sys.stderr)
    assert len(data) == 4


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
