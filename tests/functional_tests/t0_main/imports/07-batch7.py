#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.07-batch7
tag:
  shard: imports7
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 07-batch7-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 52  # sacred
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 53  # joblib
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 54  # dask
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports finish
    - 55  # asyncio
"""

import asyncio  # noqa: F401

import dask.distributed  # noqa: F401
import joblib  # noqa: F401
import sacred  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
