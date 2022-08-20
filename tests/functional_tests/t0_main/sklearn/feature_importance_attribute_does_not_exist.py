#!/usr/bin/env python
"""Tests that feature importance visualization is not produced on model without feature importances
---
id: 0.sklearn.feature_importance_attribute_does_not_exist
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
    - :op:contains_regex:
      - :wandb:runs[0][output][stderr]
      - Cannot plot feature importances
"""
import wandb
from sklearn import datasets
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier

run = wandb.init("my-scikit-integration")

wbcd = wisconsin_breast_cancer_data = datasets.load_breast_cancer()

X_train, X_test, y_train, y_test = train_test_split(
    wbcd.data, wbcd.target, test_size=0.2
)
labels = wbcd.target_names

model = KNeighborsClassifier()
model.fit(X_train, y_train)

wandb.sklearn.plot_feature_importances(model)

run.finish()
