#!/usr/bin/env python
"""Base case - main process init/finish.
"""

import wandb

wandb.init()
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
wandb.finish()
