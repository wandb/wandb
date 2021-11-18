#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.01-batch1
tag:
  shard: imports
plugin:
  - wandb
depend:
  requirements:
    - coverage  # move to yea deps
    - "-r 01-batch1-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 14  # allennlp
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 15  # autogluon
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 16  # autokeras
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 18  # catalyst
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 7  # catboost
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 19  # dalle_pytorch
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 21  # deepchem
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 22  # deepctr
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 23  # deeppavlov
"""

import wandb

import allennlp
import autogluon
import autokeras
# import avalanche
import catalyst
import catboost
import dalle_pytorch
# import datasets
import deepchem
import deepctr
import deeppavlov
# import detectron

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
