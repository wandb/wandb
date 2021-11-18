"""W&B callback for lightgbm

Really simple callback to get logging for each tree

Example usage:

param_list = [("eta", 0.08), ("max_depth", 6), ("subsample", 0.8), ("colsample_bytree", 0.8), ("alpha", 8), ("num_class", 10)]
config.update(dict(param_list))
lgb = lgb.train(param_list, d_train, callbacks=[wandb_callback()])
"""

import lightgbm
import wandb
from typing import Callable

MINIMIZE_METRICS = [
    "l1",
    "l2",
    "rmse",
    "mape",
    "huber",
    "fair",
    "poisson",
    "gamma",
    "binary_logloss",
]

MAXIMIZE_METRICS = ["map", "auc", "average_precision"]


def wandb_callback(log_params=True, define_metric=True) -> Callable:
    log_params = [log_params]
    define_metric = [define_metric]

    def _init(env):
        wandb.config.update(env.params)
        log_params[0] = False

        if define_metric[0]:
            for i in range(len(env.evaluation_result_list)):
                data_type = env.evaluation_result_list[i][0]
                metric_name = env.evaluation_result_list[i][1]
                _define_metric(data_type, metric_name)

    def _define_metric(data, metric_name):
        if "loss" in str.lower(metric_name):
            wandb.define_metric(f"{data_type}_{metric_name}", summary="min")
        elif str.lower(metric_name) in MINIMIZE_METRICS:
            wandb.define_metric(f"{data}_{metric_name}", summary="min")
        elif str.lower(metric_name) in MAXIMIZE_METRICS:
            wandb.define_metric(f"{data}_{metric_name}", summary="max")

    def _callback(env) -> None:
        if log_params[0]:
            _init(env)

        eval_results = {}
        recorder = lightgbm.record_evaluation(eval_results)
        recorder(env)

        for validation_key in eval_results.keys():
            for key in eval_results[validation_key].keys():
                wandb.log(
                    {validation_key + "_" + key: eval_results[validation_key][key][0]},
                    commit=False,
                )
        # Previous log statements use commit=False. This commits them.
        wandb.log({})

    return _callback
