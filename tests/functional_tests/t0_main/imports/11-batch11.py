#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.11-batch11
tag:
  shard: imports11
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 11-batch11-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 73  # nanodet
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 74  # segmentation_models_pytorch
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 75  # sentence_transformers
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 76  # dgl
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 78  # jina
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 79  # kornia
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 80  # albumentations
"""

import albumentations  # noqa: F401
import dgl  # noqa: F401
import jina  # noqa: F401
import kornia  # noqa: F401
import nanodet  # noqa: F401
import segmentation_models_pytorch  # noqa: F401
import sentence_transformers  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
