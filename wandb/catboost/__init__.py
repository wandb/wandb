'''W&B plot_feature_importances for catboost

Simple function to send catboost feature importances metrics to the server

Example usage:

catboost_model.fit(...)
.
.
.
wandb.catboost.plot_feature_importances(catboost_model, X_train.columns)
'''

from __future__ import absolute_import, division, print_function, unicode_literals

import numpy as np
import wandb

from .utils import test_fitted, test_types
from warnings import simplefilter

# ignore all future warnings
simplefilter(action='ignore', category=FutureWarning)


def plot_feature_importances(model=None, feature_names=None,
                             title='Feature Importance', max_num_features=50):
    """
    Evaluates & plots the importance of each feature for the classification/regressor tasks.

    Should only be called with a fitted classifer or regressor (otherwise an error is thrown).
    Only works with classifiers that have a feature_importances_ attribute.

    Arguments:
        model (clf): Takes in a fitted classifier or regressor.
        feature_names (list): Names for features. Makes plots easier to read by
                                replacing feature indexes with corresponding names.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
        wandb.catboost.plot_feature_importances(model, ['width', 'height, 'length'])
    """
    attributes_to_check = 'feature_importances_'

    if not hasattr(model, attributes_to_check):
        wandb.termwarn(
            "%s attribute not in model. Cannot plot feature importances." % attributes_to_check)
        return

    if (test_types(model=model) and test_fitted(model)):
        feature_names = np.asarray(feature_names)
        importances = model.feature_importances_

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
        print("Go to your dashboard to see the Catboost's Feature Importances graph plotted.")
        return feature_importances_table(feature_names, importances)
