#!/usr/bin/env python
"""Demonstrate non-binary plot calibration curve failure

Reproduction for WB-6749.

---
id: 0.sklearn.01-plot-calibration-curve-nonbinary
tag:
  shard: sklearn
plugin:
  - wandb
depend:
  requirements:
    - numpy
    - pandas
    - scikit-learn
  files:
    - file: wine.csv
      source: https://raw.githubusercontent.com/wandb/examples/master/examples/data/wine.csv
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][exitcode]: 0
  - :yea:exit: 0
  - :op:contains_regex:
    - :wandb:runs[0][output][stderr]
    - This function only supports binary classification at the moment and therefore expects labels to be binary
  - :op:contains:
    - :wandb:runs[0][telemetry][1]  # imports before
    - 5  # sklearn
  - :op:contains:
    - :wandb:runs[0][telemetry][2]  # imports after
    - 5  # sklearn
"""

import numpy as np
import pandas as pd
import wandb
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

# yea test will grab this
# data_url = "https://raw.githubusercontent.com/wandb/examples/master/examples/data/wine.csv"
# !wget {data_url} -O "wine.csv"

# Load data
wine_quality = pd.read_csv("wine.csv")
y = wine_quality["quality"]
y = y.values
X = wine_quality.drop(["quality"], axis=1)
X = X.values
feature_names = wine_quality.columns

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
labels = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]

# Train model, get predictions
model = RandomForestClassifier()
model.fit(X_train, y_train)
y_pred = model.predict(X_test)
y_probas = model.predict_proba(X_test)
importances = model.feature_importances_
indices = np.argsort(importances)[::-1]

print(model.n_features_)

run = wandb.init(project="my-scikit-integration")

wandb.sklearn.plot_calibration_curve(model, X_train, y_train, "RandomForestClassifier")

print(model.n_features_)

outs = model.predict(X_train)

run.finish()
