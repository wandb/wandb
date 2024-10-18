"""Define plots for regression models built with scikit-learn."""

from warnings import simplefilter

import numpy as np

import wandb
from wandb.integration.sklearn import calculate, utils

from . import shared

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def regressor(model, X_train, X_test, y_train, y_test, model_name="Regressor"):  # noqa: N803
    """Generates all sklearn regressor plots supported by W&B.

    The following plots are generated:
        learning curve, summary metrics, residuals plot, outlier candidates.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Args:
        model: (regressor) Takes in a fitted regressor.
        X_train: (arr) Training set features.
        y_train: (arr) Training set labels.
        X_test: (arr) Test set features.
        y_test: (arr) Test set labels.
        model_name: (str) Model name. Defaults to 'Regressor'

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
            under 'auto visualizations'.

    Example:
    ```python
    wandb.sklearn.plot_regressor(reg, X_train, X_test, y_train, y_test, "Ridge")
    ```
    """
    wandb.termlog(f"\nPlotting {model_name}.")

    shared.summary_metrics(model, X_train, y_train, X_test, y_test)
    wandb.termlog("Logged summary metrics.")

    shared.learning_curve(model, X_train, y_train)
    wandb.termlog("Logged learning curve.")

    outlier_candidates(model, X_train, y_train)
    wandb.termlog("Logged outlier candidates.")

    residuals(model, X_train, y_train)
    wandb.termlog("Logged residuals.")


def outlier_candidates(regressor=None, X=None, y=None):  # noqa: N803
    """Measures a datapoint's influence on regression model via cook's distance.

    Instances with high influences could potentially be outliers.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Please note this function fits the model on the training set when called.

    Args:
        model: (regressor) Takes in a fitted regressor.
        X: (arr) Training set features.
        y: (arr) Training set labels.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
    wandb.sklearn.plot_outlier_candidates(model, X, y)
    ```
    """
    is_missing = utils.test_missing(regressor=regressor, X=X, y=y)
    correct_types = utils.test_types(regressor=regressor, X=X, y=y)
    is_fitted = utils.test_fitted(regressor)

    if is_missing and correct_types and is_fitted:
        y = np.asarray(y)

        outliers_chart = calculate.outlier_candidates(regressor, X, y)
        wandb.log({"outlier_candidates": outliers_chart})


def residuals(regressor=None, X=None, y=None):  # noqa: N803
    """Measures and plots the regressor's predicted value against the residual.

    The marginal distribution of residuals is also calculated and plotted.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Please note this function fits variations of the model on the training set when called.

    Args:
        regressor: (regressor) Takes in a fitted regressor.
        X: (arr) Training set features.
        y: (arr) Training set labels.

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
    wandb.sklearn.plot_residuals(model, X, y)
    ```
    """
    not_missing = utils.test_missing(regressor=regressor, X=X, y=y)
    correct_types = utils.test_types(regressor=regressor, X=X, y=y)
    is_fitted = utils.test_fitted(regressor)

    if not_missing and correct_types and is_fitted:
        y = np.asarray(y)

        residuals_chart = calculate.residuals(regressor, X, y)
        wandb.log({"residuals": residuals_chart})
