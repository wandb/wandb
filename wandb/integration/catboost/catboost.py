# -*- coding: utf-8 -*-
"""
catboost init
"""

import wandb


class WandbCallback:
    """`WandbCallback` automatically integrates CatBoost with wandb.

    Arguments:
        - metric_period: (int) if you are passing `metric_period` to your CatBoost model please pass the same value here (default=1).

    Passing `WandbCallback` to CatBoost will:
    - log training and validation metrics at every `metric_period`
    - log iteration at every `metric_period`

    Example:
        ```
        train_pool = Pool(train[features], label=train['label'], cat_features=cat_features)
        test_pool = Pool(test[features], label=test['label'], cat_features=cat_features)

        model = CatBoostRegressor(iterations=100,
            loss_function='Cox',
            eval_metric='Cox',
        )

        model.fit(train_pool,
                  eval_set=test_pool,
                  callbacks=[WandbCallback()])
        ```
    """

    def __init__(self, metric_period: int = 1):
        if wandb.run is None:
            raise wandb.Error("You must call wandb.init() before WandbCallback()")

        self.metric_period = metric_period

    def after_iteration(self, info):
        if info.iteration % self.metric_period == 0:
            for data, metric in info.metrics.items():
                for metric_name, log in metric.items():
                    wandb.log({f"{data}-{metric_name}": log[-1]}, commit=False)

            wandb.log({f"iteration@metric-period-{self.metric_period}": info.iteration})

        return True
