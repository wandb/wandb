#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.06-batch6
tag:
  shard: imports6
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 06-batch6-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 47  # TTS
"""


import TTS  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
