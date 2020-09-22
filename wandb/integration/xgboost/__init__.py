'''W&B callback for xgboost

Really simple callback to get logging for each tree

Example usage:

param_list = [("eta", 0.08), ("max_depth", 6), ("subsample", 0.8), ("colsample_bytree", 0.8), ("objective", "multi:softmax"), ("eval_metric", "merror"), ("alpha", 8), ("lambda", 2), ("num_class", 10)]
config.update(dict(param_list))
bst = xgb.train(param_list, d_train, callbacks=[wandb_callback()])
'''

import wandb

def wandb_callback():
    def callback(env):
        for k, v in env.evaluation_result_list:
            wandb.log({k: v}, commit=False)
        wandb.log({})
    return callback