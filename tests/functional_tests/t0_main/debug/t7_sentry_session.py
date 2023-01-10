#!/usr/bin/env python
"""Base case - main process init/finish.

---
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

wandb.init()
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
# sleep needed for sentry to capture sentry session info
time.sleep(80)
