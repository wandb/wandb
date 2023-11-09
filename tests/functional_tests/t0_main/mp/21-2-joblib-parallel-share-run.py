#!/usr/bin/env python

# based on issue https://wandb.atlassian.net/browse/CLI-548
from math import sqrt

import wandb
from joblib import Parallel, delayed


def f(run, x):
    # with wandb.init() as run:
    run.config.x = x
    run.define_metric(f"step_{x}")
    for i in range(3):
        # Log metrics with wandb
        run.log({f"i_{x}": i * x, f"step_{x}": i})
    return sqrt(x)


def main():
    run = wandb.init()
    res = Parallel(n_jobs=2)(delayed(f)(run, i**2) for i in range(4))
    print(res)


if __name__ == "__main__":
    wandb.require("service")
    main()
