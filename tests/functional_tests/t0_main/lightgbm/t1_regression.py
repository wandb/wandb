#!/usr/bin/env python
"""Test lightgbm integration."""

import lightgbm as lgb
import pandas as pd
import requests
import wandb
from wandb.integration.lightgbm import log_summary, wandb_callback

# load data
# load or create your dataset
train = requests.get(
    "https://raw.githubusercontent.com/microsoft/LightGBM/master/examples/regression/regression.train"
)
test = requests.get(
    "https://raw.githubusercontent.com/microsoft/LightGBM/master/examples/regression/regression.test"
)
open("regression.train", "wb").write(train.content)
open("regression.test", "wb").write(test.content)
df_train = pd.read_csv("regression.train", header=None, sep="\t")
df_test = pd.read_csv("regression.test", header=None, sep="\t")

y_train = df_train[0]
y_test = df_test[0]
X_train = df_train.drop(0, axis=1)
X_test = df_test.drop(0, axis=1)

# create dataset for lightgbm
lgb_train = lgb.Dataset(X_train, y_train)
lgb_eval = lgb.Dataset(X_test, y_test, reference=lgb_train)

# specify your configurations as a dict
params = {
    "boosting_type": "gbdt",
    "objective": "regression",
    "metric": ["rmse", "l2", "l1", "huber", "auc"],
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbosity": -1,
    "seed": 42,
}

# initialize a new wandb project
wandb.init(project="lightgbm-reg")

# train
# add lightgbm callback
gbm = lgb.train(
    params,
    lgb_train,
    num_boost_round=10,
    valid_sets=lgb_eval,
    valid_names=("validation"),
    callbacks=[wandb_callback()],
)

log_summary(gbm, save_model_checkpoint=True)
