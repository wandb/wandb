"""ray-tune test.

Based on:
    https://docs.ray.io/en/master/tune/examples/tune-wandb.html
"""

import numpy as np
import wandb
from _test_support import get_wandb_api_key_file
from ray import tune
from ray.tune import Trainable
from ray.tune.integration.wandb import WandbTrainableMixin


class WandbTrainable(WandbTrainableMixin, Trainable):
    def step(self):
        for _i in range(30):
            loss = self.config["mean"] + self.config["sd"] * np.random.randn()
            wandb.log({"loss": loss})
        return {"loss": loss, "done": True}


def tune_trainable(api_key_file):
    """Example for using a WandTrainableMixin with the class API"""
    tuner = tune.Tuner(
        WandbTrainable,
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
    tune_trainable(api_key_file)


if __name__ == "__main__":
    main()
