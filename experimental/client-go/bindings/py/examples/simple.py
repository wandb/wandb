#!/usr/bin/env python
import wandb

run = wandb.init()
run.log({"a": 1, "b": 2, "c": 4.0, "d": "blah"})
run.finish()
