#!/usr/bin/env python
"""Test a batch of import telemetry.

---
id: 0.imports.13-batch13
tag:
  shard: imports13
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 13-batch13-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 86  # langchain
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 87  # llama-index
  - :op:contains:
    - :wandb:runs[0][telemetry][1] # imports init
    - 88 # stability-sdk
"""

import langchain  # noqa: F401
import llama_index  # noqa: F401
import stability_sdk  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
