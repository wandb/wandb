#!/usr/bin/env python
"""Test sequential runs."""

import wandb

wandb.require("service")
run1 = wandb.init()
run1.log(dict(r1a=1, r2a=2))
run1.finish()

run2 = wandb.init()
run2.log(dict(r1a=11, r2b=22))
# run2 will get finished with the script
