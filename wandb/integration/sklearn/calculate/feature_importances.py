from warnings import simplefilter

import numpy as np

import wandb

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def feature_importances(model, feature_names):
    attributes_to_check = ["feature_importances_", "feature_log_prob_", "coef_"]
    found_attribute = check_for_attribute_on(model, attributes_to_check)
    if found_attribute is None:
        wandb.termwarn(
            f"could not find any of attributes {', '.join(attributes_to_check)} on classifier. Cannot plot feature importances."
        )
        return
    elif found_attribute == "feature_importances_":
        importances = model.feature_importances_
    elif found_attribute == "coef_":  # ElasticNet-like models
        importances = model.coef_
    elif found_attribute == "feature_log_prob_":
        # coef_ was deprecated in sklearn 0.24, replaced with
        # feature_log_prob_
        importances = model.feature_log_prob_

    if len(importances.shape) > 1:
        n_significant_dims = sum(i > 1 for i in importances.shape)
        if n_significant_dims > 1:
            nd = len(importances.shape)
            wandb.termwarn(
                f"{nd}-dimensional feature importances array passed to plot_feature_importances. "
                f"{nd}-dimensional and higher feature importances arrays are not currently supported. "
                f"These importances will not be plotted."
            )
            return
        else:
            importances = np.squeeze(importances)

    indices = np.argsort(importances)[::-1]
    importances = importances[indices]

    if feature_names is None:
        feature_names = indices
    else:
        feature_names = np.array(feature_names)[indices]

    table = make_table(feature_names, importances)
    chart = wandb.visualize("wandb/feature_importances/v1", table)

    return chart


def make_table(feature_names, importances):
    table = wandb.Table(
        columns=["feature_names", "importances"],
        data=[[feature_names[i], importances[i]] for i in range(len(feature_names))],
    )
    return table


def check_for_attribute_on(model, attributes_to_check):
    for attr in attributes_to_check:
        if hasattr(model, attr):
            return attr
    return None
