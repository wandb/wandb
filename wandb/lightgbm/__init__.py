'''W&B callback for lightgbm

Really simple callback to get logging for each tree

Example usage:

param_list = [("eta", 0.08), ("max_depth", 6), ("subsample", 0.8), ("colsample_bytree", 0.8), ("alpha", 8), ("num_class", 10)]
config.update(dict(param_list))
lgb = lgb.train(param_list, d_train, callbacks=[wandb_callback()])
'''

from __future__ import absolute_import, division, print_function, unicode_literals

import numpy as np
from .utils import test_types

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


def plot_feature_importances(model=None, feature_names=None,
                             title='Feature Importance', max_num_features=50):
    """
    Evaluates & plots the importance of each feature for the gbm fitting tasks.

    Should only be called with a fitted model (otherwise an error is thrown).
    Only works with LightGBM model that have a `feature_importance` attribute.

    Arguments:
        model: Takes in a fitted gbm i.e. LightGBM
        feature_names (list): Names for features. Makes plots easier to read by
                                replacing feature indexes with corresponding names.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.lightgbm.plot_feature_importances(model, ['width', 'height, 'length'])
    """
    attributes_to_check = 'feature_importance'

    if not hasattr(model, attributes_to_check):
        wandb.termwarn(
            "%s attribute not in model. Cannot plot feature importances." % attributes_to_check)
        return

    if (test_types(model=model)):
        feature_names = np.asarray(feature_names)
        importances = model.feature_importance()

        indices = np.argsort(importances)[::-1]

        if feature_names is None:
            feature_names = indices
        else:
            feature_names = np.array(feature_names)[indices]

        max_num_features = min(max_num_features, len(importances))

        feature_names = feature_names[:max_num_features]
        importances = importances[:max_num_features]

        # Draw a stem plot with the influence for each instance
        # format:
        # x = feature_names[:max_num_features]
        # y = importances[indices][:max_num_features]
        def feature_importances_table(feature_names, importances):
            return wandb.visualize(
                'wandb/feature_importances/v1', wandb.Table(
                    columns=['feature_names', 'importances'],
                    data=[
                        [feature_names[i], importances[i]] for i in range(len(feature_names))
                    ]
                ))

        wandb.log({'feature_importances': feature_importances_table(feature_names, importances)})
        print("Go to your dashboard to see the LightGBM's Feature Importances graph plotted.")
        return feature_importances_table(feature_names, importances)
