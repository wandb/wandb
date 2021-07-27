# -*- coding: utf-8 -*-
"""Sweep config tune interface.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from wandb.sweeps.config.tune import tune

run = tune.run
loguniform = tune.loguniform
uniform = tune.uniform

__all__ = [
    "run",
    "uniform",
    "loguniform",
]

