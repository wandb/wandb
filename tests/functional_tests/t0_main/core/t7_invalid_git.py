#!/usr/bin/env python
"""Invalid git repo

---
id: 0.core.07-invalid-git
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

import os
import tempfile

import wandb

# TODO: build this kind of isolation into yea
cwd = os.getcwd()
dt = tempfile.mkdtemp()
os.chdir(dt)

try:
    os.system("git init")
    with open(os.path.join(".git", "HEAD"), "w") as f:
        f.write("INVALID")
    wandb.init()
    wandb.log(dict(m1=1))
    wandb.log(dict(m2=2))
finally:
    os.chdir(cwd)
