#!/usr/bin/env python

import wandb

wandb.require("service")
wandb.init(settings=wandb.Settings(_disable_meta=True, _disable_stats=True, _disable_viewer=True))
print("somedata")
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
wandb.finish()
