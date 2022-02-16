#!/usr/bin/env python
"""Test CatBoost integration."""

import catboost
from catboost import datasets
import wandb
from wandb.catboost import log_summary, WandbCallback

train_df, _ = datasets.msrank_10k()
X, Y = train_df[train_df.columns[1:]], train_df[train_df.columns[0]]
pool = catboost.Pool(
    data=X[:1000],
    label=Y[:1000],
    feature_names=list(X.columns)
)

cls = catboost.CatBoostClassifier(depth=2, random_seed=0, iterations=10, verbose=False)

wandb.init(project='catboost-test')
cls.fit(pool, callbacks=[WandbCallback()])
log_summary(cls, save_model_checkpoint=True)
