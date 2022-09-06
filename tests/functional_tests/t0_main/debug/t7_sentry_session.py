#!/usr/bin/env python
"""Base case - main process init/finish.

---
id: 0.core.02-with-finish
plugin:
  - wandb
tag:
  shard: standalone-cpu
var:
  - num_sentry_sessions:
      :fn:len: :wandb:sentry_sessions
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
  - :wandb:runs[0][exitcode]: 0
  - :num_sentry_sessions: 2
"""

import time

import wandb

for x in range(1):
    wandb.init()
    wandb.log(dict(m1=1))
    wandb.log(dict(m2=2))
    # sleep needed for sentry to capture session info
    time.sleep(80)
