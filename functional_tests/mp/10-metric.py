#!/usr/bin/env python

import wandb

wandb.require("service")
run = wandb.init()
print("somedata")
run.define_metric("m2", summary="max")
run.log(dict(m1=1))
run.log(dict(m2=2))
run.log(dict(m2=8))
run.log(dict(m2=4))
run.finish()
