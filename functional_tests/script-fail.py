#!/usr/bin/env python
"""Error case - main process init/finish.

---
id: 0.0.3
check-ext-wandb:
  run:
    - exit: 1
      config: {}
      summary:
        m1: 1
        m2: 2
"""

import wandb

wandb.init()
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
print(1 / 0)
