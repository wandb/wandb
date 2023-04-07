#!/usr/bin/env python
"""Base case - main process init/finish.

This test checks that two Sentry sessions are created:
one for the main process and one for the internal process.

---
plugin:
  - wandb
tag:
  shards:
    - default
    - standalone-cpu
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

import wandb

run = wandb.init()
run.log(dict(m1=1))
run.log(dict(m2=2))
