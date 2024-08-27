#!/usr/bin/env python
"""Error case - main process init/finish.

---
id: 0.core.04-multiple-init
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
      m3: 3
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][3]  # feature
    - 24  # init_return_run
"""

import wandb

run = wandb.init()
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))

# this is the same run
run2 = wandb.init()
wandb.log(dict(m3=3))
