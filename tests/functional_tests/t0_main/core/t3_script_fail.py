#!/usr/bin/env python
"""Error case - main process init/finish.

---
id: 0.core.03-script-fail
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
  - :op:contains_regex:
    - :wandb:runs[0][output][stderr]
    - ZeroDivisionError
  - :wandb:runs[0][exitcode]: 1
  - :yea:exit: 1
"""

import wandb

wandb.init()
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
print(1 / 0)
