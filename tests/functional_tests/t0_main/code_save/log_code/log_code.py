#!/usr/bin/env python
"""Code saving with log_code.

The entire subdirectory of python files will be saved by default when using
log_code()
"""

import wandb

run = wandb.init()
print(f"RUN_ID={run.id}")
run.log_code()
run.finish()
