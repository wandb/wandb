from warnings import simplefilter

import wandb
from wandb.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def residuals(
    y_pred_train,
    residuals_train,
    y_pred_test,
    residuals_test,
    train_score_,
    test_score_,
):
    y_pred_dict = []
    dataset_dict = []
    residuals_dict = []
    datapoints = 0
    max_datapoints_train = 900
    max_datapoints_train = 100
    for pred, residual in zip(y_pred_train, residuals_train):
        # add class counts from training set
        y_pred_dict.append(pred)
        dataset_dict.append("train")
        residuals_dict.append(residual)
        datapoints += 1
        if utils.check_against_limit(datapoints, max_datapoints_train, "residuals"):
            break
    datapoints = 0
    for pred, residual in zip(y_pred_test, residuals_test):
        # add class counts from training set
        y_pred_dict.append(pred)
        dataset_dict.append("test")
        residuals_dict.append(residual)
        datapoints += 1
        if utils.check_against_limit(datapoints, max_datapoints_train, "residuals"):
            break

    return wandb.visualize(
        "wandb/residuals_plot/v1",
        wandb.Table(
            columns=[
                "dataset",
                "y_pred",
                "residuals",
                "train_score",
                "test_score",
            ],
            data=[
                [
                    dataset_dict[i],
                    y_pred_dict[i],
                    residuals_dict[i],
                    train_score_,
                    test_score_,
                ]
                for i in range(len(y_pred_dict))
            ],
        ),
    )
