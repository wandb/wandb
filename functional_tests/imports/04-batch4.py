#!/usr/bin/env python
"""Test a batch of import telemetry

---
id: 0.imports.04-batch4
tag:
  shard: imports
plugin:
  - wandb
depend:
  pip_install_timeout: 1500  # 25m
  requirements:
    - "-r 04-batch4-requirements.txt"
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      loss: 1
  - :wandb:runs[0][exitcode]: 0
  # - :op:contains:
  #   - :wandb:runs[0][telemetry][1]  # imports init
  #   - 28  # pycaret
  # - :op:contains:
  #   - :wandb:runs[0][telemetry][1]  # imports init
  #   - 10  # ignite
  # - :op:contains:
  #   - :wandb:runs[0][telemetry][1]  # imports init
  #   - 30  # pytorchvideo
  # - :op:contains:
  #   - :wandb:runs[0][telemetry][1]  # imports init
  #   - 9  # pytorch_lightning
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 31  # ray
  # - :op:contains:
  #   - :wandb:runs[0][telemetry][1]  # imports init
  #   - 5  # sklearn
  # - :op:contains:
  #   - :wandb:runs[0][telemetry][1]  # imports init
  #   - 32  # simpletransformers
  # - :op:contains:
  #   - :wandb:runs[0][telemetry][1]  # imports init
  #   - 33  # skorch
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports init
    - 34  # spacy
"""

# # import paddle
# # import parlai
# # import prophet
# import pycaret  # noqa: F401

# import ignite
# import pytorchvideo  # noqa: F401
# import pytorch_lightning  # noqa: F401
import ray  # noqa: F401

# import sklearn  # noqa: F401
# import simpletransformers  # noqa: F401
# import skorch  # noqa: F401
import spacy  # noqa: F401
import wandb

run = wandb.init()
wandb.log(dict(loss=1))
run.finish()
