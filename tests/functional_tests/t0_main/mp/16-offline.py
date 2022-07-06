#!/usr/bin/env python
"""Simple offline run."""

import wandb

wandb.require("service")
wandb.init(mode="offline")
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
wandb.finish()
