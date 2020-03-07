# -*- coding: utf-8 -*-
"""Tune asynchyperband schedulers.
"""
from wandb.sweeps.config import cfg


class AsyncHyperband(cfg.SweepConfigElement):
    def __init__(self):
        super(AsyncHyperband, self).__init__()
            
    def AsyncHyperBandScheduler(self,
                 time_attr=None,
                 reward_attr=None,
                 metric=None,
                 mode=None,
                 max_t=None,
                 grace_period=None,
                 reduction_factor=None,
                 brackets=None):
        local_args = locals()
        return self._config("AsyncHyperBandScheduler", [], local_args)

AsyncHyperBandScheduler = AsyncHyperband().AsyncHyperBandScheduler


