#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.12-batch12
tag:
  shard: imports12
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - tensorflow
    - "-r 12-batch12-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 81  # keras_cv
"""

import keras_cv  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
