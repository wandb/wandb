# based on issue https://wandb.atlassian.net/browse/CLI-548

from joblib import Parallel, delayed
from math import sqrt
import wandb


def f(x):
    with wandb.init() as run:
        run.config.x = x
        for i in range(3):
            # Log metrics with wandb
            run.log({"i": i * x})
    return sqrt(x)


def main():
    res = Parallel(n_jobs=2)(delayed(f)(i ** 2) for i in range(4))
    print(res)


if __name__ == "__main__":
    wandb.require("service")
    main()
