#!/usr/bin/env python

# based on issue https://wandb.atlassian.net/browse/CLI-548
from math import sqrt

import joblib
from joblib import delayed, Parallel
import wandb

# from dask.distributed import Client


def f(run_id, x):
    # with wandb.init() as run:
    run = wandb.attach(run_id)
    run.config.x = x
    run.define_metric(f"step_{x}")
    for i in range(3):
        # Log metrics with wandb
        run.log({f"i_{x}": i * x, f"step_{x}": i})
    return sqrt(x)


def main():
    run = wandb.init()
    with joblib.parallel_backend("loky"):
        res = Parallel(n_jobs=2)(delayed(f)(run.id, i ** 2) for i in range(4))
    print(res)


if __name__ == "__main__":
    # import multiprocessing as mp
    # mp.set_start_method("spawn")
    # client = Client()
    wandb.require("service")
    main()
