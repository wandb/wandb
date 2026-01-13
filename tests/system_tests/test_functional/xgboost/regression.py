import pathlib

import numpy as np
import pandas as pd
import wandb
import xgboost as xgb
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from wandb.integration.xgboost import WandbCallback

# Generated using:
#
#   from sklearn.datasets import fetch_california_housing
#
#   fetch_california_housing(as_frame=True).frame.sample(n=100).to_csv(..., index=False)
data = pd.read_csv(pathlib.Path(__file__).parent / "regression_data.csv")

# Train validation split
x_train, x_test, y_train, y_test = train_test_split(
    data.loc[:, data.columns != "MedHouseVal"],
    data.loc[:, "MedHouseVal"],
    test_size=0.2,
    random_state=123,
)

with wandb.init(project="xgboost-housing") as run:
    xg_reg = xgb.XGBRegressor(
        objective="reg:squarederror",
        colsample_bytree=0.3,
        learning_rate=0.1,
        max_depth=5,
        alpha=10,
        n_estimators=10,
        early_stopping_rounds=20,
        tree_method="hist",
        callbacks=[WandbCallback()],
    )

    xg_reg.fit(
        x_train,
        y_train,
        eval_set=[(x_train, y_train), (x_test, y_test)],
        verbose=False,
    )

    # Evaluate
    preds = xg_reg.predict(x_test)
    rmse = np.sqrt(mean_squared_error(y_test, preds))
    run.log({"RMSE": rmse})
