#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.02-batch2
tag:
  shard: imports
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 02-batch2-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 42  # elegy
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 43  # detectron2
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 49  # huggingface_hub
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 50  # hydra
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 44  # flair
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 45  # flax
"""


import detectron2 # noqa: F401
import elegy # noqa: F401
import flair # noqa: F401
import flax # noqa: F401
import huggingface_hub # noqa: F401
import hydra # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
