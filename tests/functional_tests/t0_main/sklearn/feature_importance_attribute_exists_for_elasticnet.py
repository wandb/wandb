#!/usr/bin/env python
"""Tests that feature importance visualization is produced on elasticnet model
---
id: 0.sklearn.feature_importance_attribute_exists_for_elasticnet
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
    - :wandb:runs[0][summary][feature_importances][_type]: table-file
    - :wandb:runs[0][summary][feature_importances][ncols]: 2
    - :wandb:runs[0][summary][feature_importances][nrows]: 30
"""
import wandb
from sklearn import datasets
from sklearn.linear_model import ElasticNet
from sklearn.model_selection import train_test_split

wandb.init("my-scikit-integration")

wbcd = wisconsin_breast_cancer_data = datasets.load_breast_cancer()

X_train, X_test, y_train, y_test = train_test_split(
    wbcd.data, wbcd.target, test_size=0.2
)
labels = wbcd.target_names

model = ElasticNet()
model.fit(X_train, y_train)

wandb.sklearn.plot_feature_importances(model)
