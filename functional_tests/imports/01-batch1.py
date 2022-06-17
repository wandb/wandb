#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.01-batch1
tag:
  shard: imports1
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 01-batch1-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  #- :op:contains:
  #  - :wandb:runs[0][telemetry][1]  # imports init
  #  - 14  # allennlp
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
    - 51  # datasets
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 21  # deepchem
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 22  # deepctr
"""


# import allennlp  # noqa: F401
import autogluon  # noqa: F401
import autokeras  # noqa: F401

# import avalanche
import catalyst  # noqa: F401
import catboost  # noqa: F401

# import dalle_pytorch
import datasets  # noqa: F401
import deepchem  # noqa: F401
import deepctr  # noqa: F401

# import deeppavlov
# import detectron
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
