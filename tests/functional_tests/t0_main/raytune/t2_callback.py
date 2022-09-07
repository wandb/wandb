"""ray-tune test.

Based on:
    https://docs.ray.io/en/master/tune/examples/tune-wandb.html
"""

import numpy as np
from _test_support import get_wandb_api_key_file
from ray import air, tune
from ray.air import session
from ray.air.callbacks.wandb import WandbLoggerCallback


def objective(config, checkpoint_dir=None):
    for _i in range(30):
        loss = config["mean"] + config["sd"] * np.random.randn()
        session.report({"loss": loss})


def tune_function(api_key_file):
    """Example for using a WandbLoggerCallback with the function API"""
    tuner = tune.Tuner(
        objective,
        tune_config=tune.TuneConfig(
            metric="loss",
            mode="min",
        ),
        run_config=air.RunConfig(
            callbacks=[
                WandbLoggerCallback(api_key_file=api_key_file, project="Wandb_example")
            ],
        ),
        param_space={
            "mean": tune.grid_search([1, 2, 3, 4, 5]),
            "sd": tune.uniform(0.2, 0.8),
        },
    )
    results = tuner.fit()

    return results.get_best_result().config


def main():
    api_key_file = get_wandb_api_key_file()
    tune_function(api_key_file)


if __name__ == "__main__":
    main()
