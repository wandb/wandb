#!/usr/bin/env python
"""Test xgboost integration for classification task."""

import wandb
from sklearn.datasets import load_wine
from sklearn.model_selection import train_test_split
from wandb.integration.xgboost import wandb_callback
from xgboost import XGBClassifier

X, y = load_wine(return_X_y=True, as_frame=True)

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=1)

model = XGBClassifier(
    use_label_encoder=False, eval_metric=["mlogloss", "auc"], seed=42, n_estimators=50
)

wandb.init(project="wine-xgboost")

model.fit(
    X_train,
    y_train,
    eval_set=[(X_train, y_train), (X_test, y_test)],
    early_stopping_rounds=40,
    callbacks=[wandb_callback()],
    verbose=False,
)
