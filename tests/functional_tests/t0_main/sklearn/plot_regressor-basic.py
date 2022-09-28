#!/usr/bin/env python
"""Demonstrate basic API of plot_regressor.
---
id: 0.sklearn.plot_regressor-basic
tag:
  shard: sklearn
plugin:
    - wandb
depend:
    requirements:
        - scikit-learn
assert:
    - :wandb:runs_len: 1
    - :wandb:runs[0][exitcode]: 0
    - :yea:exit: 0
    - :wandb:runs[0][summary][learning_curve][_type]: table-file
    - :wandb:runs[0][summary][learning_curve][ncols]: 3
    - :wandb:runs[0][summary][learning_curve][nrows]: 10
    - :wandb:runs[0][summary][outlier_candidates][_type]: table-file
    - :wandb:runs[0][summary][outlier_candidates][ncols]: 4
    - :wandb:runs[0][summary][residuals][_type]: table-file
    - :wandb:runs[0][summary][residuals][ncols]: 5
    - :wandb:runs[0][summary][summary_metrics][_type]: table-file
    - :wandb:runs[0][summary][summary_metrics][ncols]: 3
    - :wandb:runs[0][summary][summary_metrics][nrows]: 3
"""
import pandas as pd
import wandb
from sklearn import datasets
from sklearn.linear_model import Ridge
from sklearn.model_selection import train_test_split

wandb.init("my-scikit-integration")

housing = datasets.fetch_california_housing()
X, y = pd.DataFrame(housing.data, columns=housing.feature_names), housing.target
X, y = X[::2], y[::2]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

model = Ridge()
model.fit(X_train, y_train)

wandb.sklearn.plot_regressor(
    model, X_train, X_test, y_train, y_test, model_name="Ridge"
)
