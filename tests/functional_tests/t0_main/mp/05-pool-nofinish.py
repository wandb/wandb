#!/usr/bin/env python
"""pool but no finish."""

import multiprocessing as mp

import wandb
import yea


def do_run(num):
    run = wandb.init()
    run.config.id = num
    run.log(dict(s=num))
    return num


def main():
    wandb.require("service")
    wandb.setup()
    num_proc = 4
    pool = mp.Pool(processes=num_proc)
    result = pool.map_async(do_run, range(num_proc))

    data = result.get(60)
    print(f"DEBUG: {data}")
    assert len(data) == 4


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
