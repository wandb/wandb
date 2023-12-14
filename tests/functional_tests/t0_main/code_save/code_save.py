#!/usr/bin/env python
"""Code saving.

The main script will be saved if enabled in the users profile settings.
"""

import wandb

run = wandb.init()
run.finish()
