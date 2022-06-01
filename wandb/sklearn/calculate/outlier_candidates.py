from warnings import simplefilter

import numpy as np

import wandb
from wandb.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def outlier_candidates(regressor, X, y):
    # Fit a linear model to X and y to compute MSE
    regressor.fit(X, y)

    # Leverage is computed as the diagonal of the projection matrix of X
    leverage = (X * np.linalg.pinv(X).T).sum(1)

    # Compute the rank and the degrees of freedom of the OLS model
    rank = np.linalg.matrix_rank(X)
    df = X.shape[0] - rank

    # Compute the MSE from the residuals
    residuals = y - regressor.predict(X)
    mse = np.dot(residuals, residuals) / df

    # Compute Cook's distance
    residuals_studentized = residuals / np.sqrt(mse) / np.sqrt(1 - leverage)
    distance_ = residuals_studentized**2 / X.shape[1]
    distance_ *= leverage / (1 - leverage)

    # Compute the influence threshold rule of thumb
    influence_threshold_ = 4 / X.shape[0]
    outlier_percentage_ = sum(distance_ >= influence_threshold_) / X.shape[0]
    outlier_percentage_ *= 100.0

    distance_dict, count = [], 0
    for d in distance_:
        distance_dict.append(d)
        count += 1
        if utils.check_against_limit(
            count,
            "outlier_candidates",
            utils.chart_limit,
        ):
            break

    table = make_table(distance_dict, outlier_percentage_, influence_threshold_)
    chart = wandb.visualize("wandb/outliers/v1", table)

    return chart


def make_table(distance, outlier_percentage, influence_threshold):
    columns = [
        "distance",
        "instance_indicies",
        "outlier_percentage",
        "influence_threshold",
    ]

    data = [
        [distance[i], i, utils.round_3(outlier_percentage), influence_threshold]
        for i in range(len(distance))
    ]

    table = wandb.Table(columns=columns, data=data)

    return table
