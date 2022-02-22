#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.03-batch3
tag:
  shard: imports
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 03-batch3-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 34  # flash
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 35  # recbole
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 36  # optuna
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 37  # mmcv
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 38  # mmdet
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 48  # monai
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 39  # torchdrug
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 40  # torchtext
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 41  # torchvision
"""


import flash  # noqa: F401
import mmcv  # noqa: F401
import mmdet  # noqa: F401
import monai  # noqa: F401
import optuna  # noqa: F401
import recbole  # noqa: F401
import torchdrug  # noqa: F401
import torchtext  # noqa: F401
import torchvision  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
