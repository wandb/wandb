#!/usr/bin/env python

import os
import time

import wandb

stats_settings = wandb.Settings(
    _stats_sample_rate_seconds=0.5, _stats_samples_to_average=2
)
wandb.init(settings=stats_settings)
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
time.sleep(5)
