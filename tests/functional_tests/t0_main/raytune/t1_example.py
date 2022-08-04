"""ray-tune test.

Based on:
    https://docs.wandb.ai/guides/integrations/other/ray-tune
"""

import os

from ray import tune
from ray.tune.integration.wandb import wandb_mixin
import wandb

from _test_support import get_wandb_api_key


@wandb_mixin
def train_fn(config):
    for i in range(10):
        loss = config["a"] + config["b"]
        wandb.log({"loss": loss})
        tune.report(loss=loss)


tune.run(
    train_fn,
    config={
        # define search space here
        "a": tune.choice([1, 2, 3]),
        "b": tune.choice([4, 5, 6]),
        # wandb configuration
        "wandb": {
            "project": "Optimization_Project",
            "api_key": get_wandb_api_key()
        }
    })
