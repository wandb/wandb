#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.03-batch3
tag:
  shard: imports3
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  pip_install_options:
    - -f
    - https://download.pytorch.org/whl/cpu/torch_stable.html
    - -qq
  requirements:
    - torch
    - -r 03-batch3-requirements.txt
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 34  # flash
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 35  # recbole
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 36  # optuna
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 37  # mmcv
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 38  # mmdet
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 48  # monai
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 39  # torchdrug
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 40  # torchtext
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
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
