#!/usr/bin/env python
"""Demonstrate basic API of plot_learning_curve.
---
id: 0.sklearn.plot_learning_curve-basic
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
"""
import wandb
from sklearn import datasets
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

wandb.init("my-scikit-integration")

wbcd = wisconsin_breast_cancer_data = datasets.load_breast_cancer()

X_train, _, y_train, _ = train_test_split(wbcd.data, wbcd.target, test_size=0.2)

model = RandomForestClassifier()
model.fit(X_train, y_train)

wandb.sklearn.plot_learning_curve(model, X_train, y_train)
