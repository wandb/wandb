#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.01-batch1
tag:
  shard: imports
plugin:
  - wandb
depend:
  requirements:
    - "-r 01-batch1-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
  - :wandb:runs[0][exitcode]: 0
"""

import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
