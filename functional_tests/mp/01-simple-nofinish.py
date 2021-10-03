#!/usr/bin/env python

import wandb

wandb.require("concurrency")
wandb.init()
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
