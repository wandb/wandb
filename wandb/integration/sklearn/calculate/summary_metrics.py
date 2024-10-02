from warnings import simplefilter

import numpy as np
import sklearn

import wandb
from wandb.integration.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def summary_metrics(model=None, X=None, y=None, X_test=None, y_test=None):  # noqa: N803
    """Calculate summary metrics for both regressors and classifiers.

    Called by plot_summary_metrics to visualize metrics. Please use the function
    plot_summary_metrics() if you wish to visualize your summary metrics.
    """
    y, y_test = np.asarray(y), np.asarray(y_test)
    metrics = {}
    model_name = model.__class__.__name__

    y_pred = model.predict(X_test)

    if sklearn.base.is_classifier(model):
        accuracy_score = sklearn.metrics.accuracy_score(y_test, y_pred)
        metrics["accuracy_score"] = accuracy_score

        precision = sklearn.metrics.precision_score(y_test, y_pred, average="weighted")
        metrics["precision"] = precision

        recall = sklearn.metrics.recall_score(y_test, y_pred, average="weighted")
        metrics["recall"] = recall

        f1_score = sklearn.metrics.f1_score(y_test, y_pred, average="weighted")
        metrics["f1_score"] = f1_score

    elif sklearn.base.is_regressor(model):
        mae = sklearn.metrics.mean_absolute_error(y_test, y_pred)
        metrics["mae"] = mae

        mse = sklearn.metrics.mean_squared_error(y_test, y_pred)
        metrics["mse"] = mse

        r2_score = sklearn.metrics.r2_score(y_test, y_pred)
        metrics["r2_score"] = r2_score

    metrics = {name: utils.round_2(metric) for name, metric in metrics.items()}

    table = make_table(metrics, model_name)
    chart = wandb.visualize("wandb/metrics/v1", table)

    return chart


def make_table(metrics, model_name):
    columns = ["metric_name", "metric_value", "model_name"]
    table_content = [[name, value, model_name] for name, value in metrics.items()]

    table = wandb.Table(columns=columns, data=table_content)

    return table
