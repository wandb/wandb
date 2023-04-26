"""ray-tune test.

Based on:
    https://docs.ray.io/en/master/tune/examples/tune-wandb.html
"""

import numpy as np
from _test_support import get_wandb_api_key_file
from ray import tune
from ray.air import session
from ray.air.integrations.wandb import setup_wandb


def train_function_wandb(config):
    run = setup_wandb(config)

    for _ in range(30):
        loss = config["mean"] + config["sd"] * np.random.randn()
        session.report({"loss": loss})
        run.log(dict(loss=loss))


def tune_with_setup():
    """Example for using the setup_wandb utility with the function API."""
    api_key_file = get_wandb_api_key_file()

    tuner = tune.Tuner(
        train_function_wandb,
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


if __name__ == "__main__":
    tune_with_setup()
