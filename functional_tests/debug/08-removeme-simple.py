#!/usr/bin/env python
"""Base case - main process init/finish.

---
id: 0.core.02-with-finish
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][3]  # feature
    - 2  # finish
"""

import time
start = time.time()
import wandb
wandb.init()
print("startup:", time.time() - start)

wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
import time
wandb.finish()
