#!/usr/bin/env python
"""Demonstrate basic API of plot_classifier.
---
id: 0.sklearn.plot_classifer-basic
plugin:
    - wandb
depend:
    requirements:
        - scikit-learn
assert:
    - :wandb:runs_len: 1
    - :wandb:runs[0][exitcode]: 0
    - :yea:exit: 0
"""
import wandb
from sklearn import datasets
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

wandb.init("my-scikit-integration")

wbcd = wisconsin_breast_cancer_data = datasets.load_breast_cancer()

X_train, X_test, y_train, y_test = train_test_split(wbcd.data, wbcd.target, test_size=0.2)
labels = wbcd.target_names

model = RandomForestClassifier()
model.fit(X_train, y_train)

y_pred, y_probas = model.predict(X_test), model.predict_proba(X_test)

wandb.sklearn.plot_classifier(model,
                              X_train, X_test,
                              y_train, y_test,
                              y_pred, y_probas,
                              labels,
                              is_binary=True,
                              model_name="RandomForest")
