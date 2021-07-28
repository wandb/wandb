#!/usr/bin/env python
"""Test Optuna integration
---
id: 0.0.4
check-ext-wandb: {}
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][project]: integrations_testing
  - :wandb:runs[0][config][a]: 2
    - :wandb:runs[0][config][b]: testing
  - :wandb:runs[0][exitcode]: 0
"""

import torch
import deepchem as dc
from deepchem.models.wandblogger import WandbLogger
from deepchem.models.losses import L2Loss
from deepchem.metrics import Metric, mae_score, pearson_r2_score

# Import datasets
tasks, datasets, transformers = dc.molnet.load_delaney(
    featurizer="ECFP", splitter="random"
)
train_dataset, valid_dataset, test_dataset = datasets

# Initialize Logger
wandblogger = WandbLogger()

# Set up Pytorch Model
pytorch_model = torch.nn.Sequential(
    torch.nn.Linear(1024, 1000), torch.nn.Dropout(p=0.5), torch.nn.Linear(1000, 1)
)

model = dc.models.TorchModel(
    pytorch_model,
    L2Loss(),
    logger=wandblogger,
    model_dir="./testing_train_checkpoints",
)

# Set up metrics
metric = Metric(pearson_r2_score)
metric2 = Metric(mae_score)

# Set up validation callback
vc_valid = dc.models.ValidationCallback(
    valid_dataset,
    10,
    [metric, metric2],
    save_dir="./testing_val_checkpoints",
    save_on_minimum=False,
    name="callback2",
)

# Train model while log evaluation metrics
model.fit(train_dataset, nb_epoch=3, checkpoint_interval=1, callbacks=[vc_valid])
wandblogger.finish()
