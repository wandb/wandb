#!/usr/bin/env python
"""Invalid git repo

---
id: 0.core.07-invalid-git
tag:
  platforms:
    - win
    - linux
  skips:
    - platform: mac
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
  - :wandb:runs[0][exitcode]: 0
"""

import wandb
import os

with open(os.path.join(".git", "HEAD"), "w") as f:
    f.write("INVALID")

wandb.init()
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
