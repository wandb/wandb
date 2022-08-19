#!/usr/bin/env python
"""Test CatBoost integration."""

import wandb
from catboost import CatBoostClassifier, Pool, datasets
from wandb.catboost import WandbCallback, log_summary

train_df, _ = datasets.msrank_10k()
X, Y = train_df[train_df.columns[1:]], train_df[train_df.columns[0]]
pool = Pool(
    data=X[:1000],
    label=Y[:1000],
    feature_names=list(X.columns),
)

classifier = CatBoostClassifier(depth=2, random_seed=0, iterations=10, verbose=False)

wandb.init(project="catboost-test")
classifier.fit(pool, callbacks=[WandbCallback()])
log_summary(classifier, save_model_checkpoint=True)
