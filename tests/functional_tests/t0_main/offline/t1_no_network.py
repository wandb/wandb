#!/usr/bin/env python
"""Simple offline run.

---
id: 0.offline.01-no-network
env:
  - WANDB_BASE_URL: https://does.not-resolve/
command:
  timeout: 20
plugin:
  - wandb
assert:
  - :wandb:runs_len: 0
  - :yea:exit: 0
"""

import wandb

run = wandb.init(mode="offline")
run.log(dict(m1=1))
run.log(dict(m2=2))
run.finish()
