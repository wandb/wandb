"""ray-tune test.

Based on:
    https://docs.ray.io/en/master/tune/examples/tune-wandb.html
"""

import numpy as np
import wandb
from _test_support import get_wandb_api_key_file
from ray import tune
from ray.air import session
from ray.tune.integration.wandb import wandb_mixin


@wandb_mixin
def decorated_objective(config, checkpoint_dir=None):
    for _i in range(30):
        loss = config["mean"] + config["sd"] * np.random.randn()
        session.report({"loss": loss})
        wandb.log(dict(loss=loss))


def tune_decorated(api_key_file):
    """Example for using the @wandb_mixin decorator with the function API"""
    tuner = tune.Tuner(
        decorated_objective,
        tune_config=tune.TuneConfig(
            metric="loss",
            mode="min",
        ),
        param_space={
            "mean": tune.grid_search([1, 2, 3, 4, 5]),
            "sd": tune.uniform(0.2, 0.8),
            "wandb": {"api_key_file": api_key_file, "project": "Wandb_example"},
        },
    )
    results = tuner.fit()

    return results.get_best_result().config


def main():
    api_key_file = get_wandb_api_key_file()
    tune_decorated(api_key_file)


if __name__ == "__main__":
    main()
