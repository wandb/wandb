#!/usr/bin/env python

# based on issue https://wandb.atlassian.net/browse/CLI-548
from math import sqrt

import wandb
from joblib import Parallel, delayed


def f(x):
    with wandb.init() as run:
        run.config.x = x
        for i in range(3):
            # Log metrics with wandb
            run.log({"i": i * x})
    return sqrt(x)


def main():
    res = Parallel(n_jobs=2)(delayed(f)(i**2) for i in range(4))
    print(res)


if __name__ == "__main__":
    wandb.require("service")
    main()
