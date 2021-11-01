from warnings import simplefilter

import numpy as np
import sklearn

import wandb
from wandb.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def summary_metrics(model=None, X=None, y=None, X_test=None, y_test=None):
    """Calculates summary metrics for both regressors and classifiers.

    Called by plot_summary_metrics to visualize metrics. Please use the function
    plot_summary_metrics() if you wish to visualize your summary metrics.
    """
    if (
        utils.test_missing(model=model, X=X, y=y, X_test=X_test, y_test=y_test)
        and utils.test_types(model=model, X=X, y=y, X_test=X_test, y_test=y_test)
        and utils.test_fitted(model)
    ):
        y = np.asarray(y)
        y_test = np.asarray(y_test)
        metric_name = []
        metric_value = []
        model_name = model.__class__.__name__

        params = {}
        # Log model params to wandb.config
        for v in vars(model):
            if (
                isinstance(getattr(model, v), str)
                or isinstance(getattr(model, v), bool)
                or isinstance(getattr(model, v), int)
                or isinstance(getattr(model, v), float)
            ):
                params[v] = getattr(model, v)

        # Classifier Metrics
        if sklearn.base.is_classifier(model):
            y_pred = model.predict(X_test)

            metric_name.append("accuracy_score")
            metric_value.append(
                utils.round_2(sklearn.metrics.accuracy_score(y_test, y_pred))
            )
            metric_name.append("precision")
            metric_value.append(
                utils.round_2(
                    sklearn.metrics.precision_score(y_test, y_pred, average="weighted")
                )
            )
            metric_name.append("recall")
            metric_value.append(
                utils.round_2(
                    sklearn.metrics.recall_score(y_test, y_pred, average="weighted")
                )
            )
            metric_name.append("f1_score")
            metric_value.append(
                utils.round_2(
                    sklearn.metrics.f1_score(y_test, y_pred, average="weighted")
                )
            )

        # Regression Metrics
        elif sklearn.base.is_regressor(model):
            y_pred = model.predict(X_test)

            metric_name.append("mae")
            metric_value.append(
                utils.round_2(sklearn.metrics.mean_absolute_error(y_test, y_pred))
            )
            metric_name.append("mse")
            metric_value.append(
                utils.round_2(sklearn.metrics.mean_squared_error(y_test, y_pred))
            )
            metric_name.append("r2_score")
            metric_value.append(utils.round_2(sklearn.metrics.r2_score(y_test, y_pred)))

        return wandb.visualize(
            "wandb/metrics/v1",
            wandb.Table(
                columns=["metric_name", "metric_value", "model_name"],
                data=[
                    [metric_name[i], metric_value[i], model_name]
                    for i in range(len(metric_name))
                ],
            ),
        )
