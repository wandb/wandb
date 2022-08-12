#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.05-batch5
tag:
  shard: imports5
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 05-batch5-requirements.txt"
    - "flask>=2.2.2"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 46  # syft
"""


import syft  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
