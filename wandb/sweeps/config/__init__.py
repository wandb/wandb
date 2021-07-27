# -*- coding: utf-8 -*-
"""Sweep config interface.

Example:
    from wandb.sweeps import configure as cfg
    ray_config = cfg.tune.run(
        search_algo = cfg.tune.suggest.hyperopt.HyperOptSearch(
            space = {
                'width': cfg.hp.uniform('width', 0, 20),
                'height': cfg.hp.uniform('height', -100, 100),
                'activation': cfg.hp.choice("activation", ["relu", "tanh"])
            },
            max_concurrent = 4,
            reward_attr = "neg_mean_loss"
        ),
        scheduler = cfg.tune.schedulers.AsyncHyperBandScheduler(reward_attr="neg_mean_loss"),
        num_samples = 10 if args.smoke_test else 1000,
        config = {
            "iterations": 100,
        },
        stop = {
            "timesteps_total": 100
        },
    )
    id = wandb.sweep(ray_config)
    print("id:", id)
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

#from wandb.sweeps.config.tune import tune
from wandb.sweeps.config.cfg import SweepConfig
#from wandb.sweeps.config import hyperopt

__all__ = [
    "tune",
    "SweepConfig",
]

