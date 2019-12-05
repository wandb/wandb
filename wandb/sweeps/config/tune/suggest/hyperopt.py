# -*- coding: utf-8 -*-
"""Tune hyperopt generation.
"""
from wandb.sweeps.config import cfg


class HyperOpt(cfg.SweepConfigElement):
    def __init__(self):
        super(HyperOpt, self).__init__()
            
    def HyperOptSearch(self,
                 space,
                 max_concurrent=None,
                 reward_attr=None,
                 metric=None,
                 mode=None,
                 points_to_evaluate=None,
                 n_initial_points=None,
                 random_state_seed=None,
                 gamma=None,
                 **kwargs):
        local_args = locals()
        return self._config("hyperopt.HyperOptSearch", [], local_args)

HyperOptSearch = HyperOpt().HyperOptSearch


