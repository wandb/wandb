'''W&B callback for lightgbm

Really simple callback to get logging for each tree

Example usage:

param_list = [("eta", 0.08), ("max_depth", 6), ("subsample", 0.8), ("colsample_bytree", 0.8), ("alpha", 8), ("num_class", 10)]
config.update(dict(param_list))
lgb = lgb.train(param_list, d_train, callbacks=[wandb_callback()])
'''

import lightgbm
import wandb


def wandb_callback():
    def callback(env):
        eval_results = {}
        recorder = lightgbm.record_evaluation(eval_results)
        recorder(env)

        for validation_key in eval_results.keys():
            for key in eval_results[validation_key].keys():
                wandb.log({
                    validation_key + "_" + key: eval_results[validation_key][key][0]
                }, commit=False)
        # Previous log statements use commit=False. This commits them.
        wandb.log({})
    return callback
