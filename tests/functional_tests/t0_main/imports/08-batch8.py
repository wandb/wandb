#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.08-batch8
tag:
  shard: imports8
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 08-batch8-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 56  # paddleocr
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 57  # ppdet
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 58  # paddleseg
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 59  # paddlenlp
"""

import paddlenlp  # noqa: F401
import paddleocr  # noqa: F401
import paddleseg  # noqa: F401
import ppdet  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
