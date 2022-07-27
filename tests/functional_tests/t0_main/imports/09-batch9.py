#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.09-batch9
tag:
  shard: imports9
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 09-batch9-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 60  # mmseg
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 61  # mmocr
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 62  # mmcls
"""

import mmcls  # noqa: F401
import mmocr  # noqa: F401
import mmseg  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
