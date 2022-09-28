#!/usr/bin/env python
"""Demonstrate basic API of plot_summary_metrics.
---
id: 0.sklearn.plot_summary_metrics-basic
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
    - :wandb:runs[0][summary][summary_metrics][_type]: table-file
    - :wandb:runs[0][summary][summary_metrics][ncols]: 3
    - :wandb:runs[0][summary][summary_metrics][nrows]: 4
"""
import wandb
from sklearn import datasets
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

wandb.init("my-scikit-integration")

wbcd = wisconsin_breast_cancer_data = datasets.load_breast_cancer()

X_train, X_test, y_train, y_test = train_test_split(
    wbcd.data, wbcd.target, test_size=0.2
)

model = RandomForestClassifier()
model.fit(X_train, y_train)

wandb.sklearn.plot_summary_metrics(model, X_train, y_train, X_test, y_test)
