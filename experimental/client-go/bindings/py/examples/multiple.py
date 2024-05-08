#!/usr/bin/env python
import wandb

runs = [wandb.init() for x in range(10)]
for run in runs:
    run.log({"a": 1, "b": 2, "c": 4.0, "d": "blah"})
for run in runs:
    run.finish()
