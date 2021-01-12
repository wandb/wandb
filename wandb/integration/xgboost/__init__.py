"""W&B callback for xgboost

Really simple callback to get logging for each tree

Example usage:

param_list = [("eta", 0.08), ("max_depth", 6), ("subsample", 0.8), ("colsample_bytree", 0.8), ("objective", "multi:softmax"), ("eval_metric", "merror"), ("alpha", 8), ("lambda", 2), ("num_class", 10)]
config.update(dict(param_list))
bst = xgb.train(param_list, d_train, callbacks=[wandb_callback()])
"""

import wandb
import xgboost

class WandbCallback(xgboost.callback.TrainingCallback):
    def __init__(self):
        pass

    def _get_key(self, data, metric):
        return f'{data}-{metric}'

    def after_iteration(self, model, epoch, evals_log):
        for data, metric in evals_log.items():
            for metric_name, log in metric.items():
                key = self._get_key(data, metric_name) 
                wandb.log({key: log[-1]}, commit=False)
        wandb.log({})

def wandb_callback():
    return WandbCallback()