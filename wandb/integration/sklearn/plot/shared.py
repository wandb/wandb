"""Define plots used by multiple sklearn model classes."""

from warnings import simplefilter

import numpy as np

import wandb
from wandb.integration.sklearn import calculate, utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def summary_metrics(model=None, X=None, y=None, X_test=None, y_test=None):  # noqa: N803
    """Logs a chart depicting summary metrics for a model.

    Should only be called with a fitted model (otherwise an error is thrown).

    Arguments:
        model: (clf or reg) Takes in a fitted regressor or classifier.
        X: (arr) Training set features.
        y: (arr) Training set labels.
        X_test: (arr) Test set features.
        y_test: (arr) Test set labels.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
    wandb.sklearn.plot_summary_metrics(model, X_train, y_train, X_test, y_test)
    ```
    """
    not_missing = utils.test_missing(
        model=model, X=X, y=y, X_test=X_test, y_test=y_test
    )
    correct_types = utils.test_types(
        model=model, X=X, y=y, X_test=X_test, y_test=y_test
    )
    model_fitted = utils.test_fitted(model)

    if not_missing and correct_types and model_fitted:
        metrics_chart = calculate.summary_metrics(model, X, y, X_test, y_test)
        wandb.log({"summary_metrics": metrics_chart})


def learning_curve(
    model=None,
    X=None,  # noqa: N803
    y=None,
    cv=None,
    shuffle=False,
    random_state=None,
    train_sizes=None,
    n_jobs=1,
    scoring=None,
):
    """Logs a plot depicting model performance against dataset size.

    Please note this function fits the model to datasets of varying sizes when called.

    Arguments:
        model: (clf or reg) Takes in a fitted regressor or classifier.
        X: (arr) Dataset features.
        y: (arr) Dataset labels.

    For details on the other keyword arguments, see the documentation for
    `sklearn.model_selection.learning_curve`.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
    wandb.sklearn.plot_learning_curve(model, X, y)
    ```
    """
    not_missing = utils.test_missing(model=model, X=X, y=y)
    correct_types = utils.test_types(model=model, X=X, y=y)
    if not_missing and correct_types:
        if train_sizes is None:
            train_sizes = np.linspace(0.1, 1.0, 5)
        y = np.asarray(y)

        learning_curve_chart = calculate.learning_curve(
            model, X, y, cv, shuffle, random_state, train_sizes, n_jobs, scoring
        )

        wandb.log({"learning_curve": learning_curve_chart})
