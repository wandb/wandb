from __future__ import annotations

import pathlib

import pandas as pd
import wandb
from sklearn.model_selection import train_test_split
from wandb.integration.xgboost import WandbCallback
from xgboost import XGBClassifier

# Generated using:
#
#   from sklearn.datasets import load_wine
#
#   load_wine(as_frame=True).frame.sample(n=100).to_csv(..., index=False)
data = pd.read_csv(pathlib.Path(__file__).parent / "classification_data.csv")

x_train, x_test, y_train, y_test = train_test_split(
    data.loc[:, data.columns != "target"],
    data.loc[:, "target"],
    test_size=0.3,
    random_state=1,
)

with wandb.init(project="wine-xgboost"):
    model = XGBClassifier(
        eval_metric=["mlogloss", "auc"],
        seed=42,
        n_estimators=20,
        early_stopping_rounds=40,
        callbacks=[WandbCallback(log_model=True)],
    )

    model.fit(
        x_train,
        y_train,
        eval_set=[(x_train, y_train), (x_test, y_test)],
        verbose=False,
    )
