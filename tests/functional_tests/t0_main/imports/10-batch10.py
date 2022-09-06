#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.10-batch10
tag:
  shard: imports10
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 10-batch10-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 63  # timm
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 64  # fairseq
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 65  # deepchecks
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 66  # composer
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 67  # sparseml
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 69  # zenml
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 71  # accelerate
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 72  # merlin
"""

import accelerate  # noqa: F401
import composer  # noqa: F401
import deepchecks  # noqa: F401
import fairseq  # noqa: F401
import merlin  # noqa: F401
import sparseml  # noqa: F401
import timm  # noqa: F401
import wandb
import zenml  # noqa: F401

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
