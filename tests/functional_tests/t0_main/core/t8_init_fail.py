#!/usr/bin/env python
"""Check init failing with atexit finishall.

---
plugin:
  - wandb
command:
  timeout: 30
env:
  - WANDB_INIT_TIMEOUT: "8"
  - WANDB_BASE_URL: http://localhost:9999/bad/bad
  - WANDB_API_KEY: thisisnotavalidkey
assert:
  - :wandb:runs_len: 0
  - :yea:exit: 0
"""

import wandb

try:
    wandb.init()
except wandb.errors.CommError:
    pass
