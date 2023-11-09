#!/usr/bin/env python

import wandb

wandb.require("service")
wandb.init()
print("somedata")
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
wandb.finish()
