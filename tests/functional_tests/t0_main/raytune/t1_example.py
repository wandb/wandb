"""ray-tune test.

Based on:
    https://docs.wandb.ai/guides/integrations/ray-tune
"""

import random

import numpy as np
from _test_support import get_wandb_api_key
from ray import tune
from ray.air.integrations.wandb import setup_wandb


def train_fn(config):
    run = setup_wandb(config)
    for _i in range(10):
        loss = config["a"] + config["b"]
        run.log({"loss": loss})
        tune.report(loss=loss)
    run.finish()


def main():
    # Make test deterministic
    random.seed(2022)
    np.random.seed(2022)

    tune.run(
        train_fn,
        config={
            # define search space here
            "a": tune.choice([1, 2, 3]),
            "b": tune.choice([4, 5, 6]),
            # wandb configuration
            "wandb": {
                "project": "Optimization_Project",
                "api_key": get_wandb_api_key(),
            },
        },
    )


if __name__ == "__main__":
    main()
