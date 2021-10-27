#!/usr/bin/env python

import wandb

wandb.require("service")
wandb.setup()
run = wandb.init()
run.log(dict(m1=1))
run.log(dict(m2=2))
wandb.teardown()
