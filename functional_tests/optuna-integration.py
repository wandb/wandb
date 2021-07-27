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

import wandb
import optuna
from optuna.integration.wandb import WeightsAndBiasesCallback

def objective(trial):
    x = trial.suggest_float("x", -10, 10)
    return (x - 2) ** 2

n_trials=5
wandb_kwargs = {"project": "integrations_testing", "config":{"a":2, "b":"testing"}}
wandbc = WeightsAndBiasesCallback(wandb_kwargs=wandb_kwargs)
study = optuna.create_study(study_name="my_study")
study.optimize(objective, n_trials=n_trials, callbacks=[wandbc])
wandb.finish()