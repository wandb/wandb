#!/usr/bin/env python
"""Demonstrate basic API of plot_classifier.
---
id: 0.sklearn.plot_classifer-basic
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
    - :wandb:runs[0][summary][calibration_curve][_type]: table-file
    - :wandb:runs[0][summary][calibration_curve][ncols]: 5
    - :wandb:runs[0][summary][class_proportions][_type]: table-file
    - :wandb:runs[0][summary][class_proportions][ncols]: 3
    - :wandb:runs[0][summary][class_proportions][nrows]: 4
    - :wandb:runs[0][summary][confusion_matrix][_type]: table-file
    - :wandb:runs[0][summary][confusion_matrix][ncols]: 3
    - :wandb:runs[0][summary][confusion_matrix][nrows]: 4
    - :wandb:runs[0][summary][feature_importances][_type]: table-file
    - :wandb:runs[0][summary][feature_importances][ncols]: 2
    - :wandb:runs[0][summary][feature_importances][nrows]: 30
    - :wandb:runs[0][summary][precision_recall][_type]: table-file
    - :wandb:runs[0][summary][precision_recall][ncols]: 3
    - :wandb:runs[0][summary][precision_recall][nrows]: 40
    - :wandb:runs[0][summary][roc][_type]: table-file
    - :wandb:runs[0][summary][roc][ncols]: 3
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
labels = wbcd.target_names

model = RandomForestClassifier()
model.fit(X_train, y_train)

y_pred, y_probas = model.predict(X_test), model.predict_proba(X_test)

wandb.sklearn.plot_classifier(
    model,
    X_train,
    X_test,
    y_train,
    y_test,
    y_pred,
    y_probas,
    labels,
    is_binary=True,
    model_name="RandomForest",
)
