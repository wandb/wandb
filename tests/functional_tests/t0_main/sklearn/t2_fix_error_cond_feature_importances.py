#!/usr/bin/env python
"""Demonstrate fix for error condition for plotting feature importances in sklearn

Reproduction for WB-6697

---
id: 0.sklearn.02-fix-error-cond-feature-importances
tag:
  shard: sklearn
plugin:
  - wandb
depend:
  requirements:
    - sklearn
    - numpy
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][exitcode]: 0
  - :yea:exit: 0
  - :op:not_contains_regex:
    - :wandb:runs[0][output][stderr]
    - These importances will not be plotted
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports before
    - 5  # sklearn
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports after
    - 5  # sklearn
"""

import numpy as np
import wandb
from sklearn.linear_model import LogisticRegression

run = wandb.init()

# Load data
X = np.random.uniform(size=(100, 10))

# binary classification problem
y = np.round(np.random.uniform(size=100)).astype(int)

# Train model, log feature importances.
model = LogisticRegression()
model.fit(X, y)

# before the fix in wb-6697 this should have produced a warning and
# caused the feature importances not to be logged
wandb.sklearn.plot_feature_importances(model)

run.finish()
