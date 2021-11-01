"""Logs sklearn model plots to W&B."""
from warnings import simplefilter

import numpy as np
from sklearn import model_selection

import wandb

from wandb.sklearn import utils
from wandb.sklearn import calculate

from . import shared

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def regressor(model, X_train, X_test, y_train, y_test, model_name="Regressor"):
    """Generates all sklearn regressor plots supported by W&B.

    The following plots are generated:
        learning curve, summary metrics, residuals plot, outlier candidates.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Arguments:
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
        wandb.sklearn.plot_regressor(reg, X_train, X_test, y_train, y_test, 'Ridge')
    ```
    """
    wandb.termlog("\nPlotting %s." % model_name)
    shared.plot_summary_metrics(model, X_train, y_train, X_test, y_test)
    wandb.termlog("Logged summary metrics.")
    shared.plot_learning_curve(model, X_train, y_train)
    wandb.termlog("Logged learning curve.")
    outlier_candidates(model, X_train, y_train)
    wandb.termlog("Logged outlier candidates.")
    residuals(model, X_train, y_train)
    wandb.termlog("Logged residuals.")


def outlier_candidates(regressor=None, X=None, y=None):
    """Measures a datapoint's influence on regression model via cook's distance.

    Instances with high influences could potentially be outliers.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Please note this function fits the model on the training set when called.

    Arguments:
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
    if (
        utils.test_missing(regressor=regressor, X=X, y=y)
        and utils.test_types(regressor=regressor, X=X, y=y)
        and utils.test_fitted(regressor)
    ):
        y = np.asarray(y)
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
        distance_ = residuals_studentized ** 2 / X.shape[1]
        distance_ *= leverage / (1 - leverage)

        # Compute the influence threshold rule of thumb
        influence_threshold_ = 4 / X.shape[0]
        outlier_percentage_ = sum(distance_ >= influence_threshold_) / X.shape[0]
        outlier_percentage_ *= 100.0

        distance_dict = []
        count = 0
        for d in distance_:
            distance_dict.append(d)
            count += 1
            if utils.check_against_limit(
                count, utils.chart_limit, "outlier_candidates"
            ):
                break

        wandb.log(
            {
                "outlier_candidates": calculate.outlier_candidates(
                    distance_dict, outlier_percentage_, influence_threshold_
                )
            }
        )
        return


def residuals(regressor=None, X=None, y=None):
    """Measures and plots the regressor's predicted value against the residual.

    The marginal distribution of residuals is also calculated and plotted.

    Should only be called with a fitted regressor (otherwise an error is thrown).

    Please note this function fits variations of the model on the training set when called.

    Arguments:
        model: (regressor) Takes in a fitted regressor.
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
    if (
        utils.test_missing(regressor=regressor, X=X, y=y)
        and utils.test_types(regressor=regressor, X=X, y=y)
        and utils.test_fitted(regressor)
    ):
        y = np.asarray(y)
        # Create the train and test splits
        X_train, X_test, y_train, y_test = model_selection.train_test_split(
            X, y, test_size=0.2
        )

        # Store labels and colors for the legend ordered by call
        regressor.fit(X_train, y_train)
        train_score_ = regressor.score(X_train, y_train)
        test_score_ = regressor.score(X_test, y_test)

        y_pred_train = regressor.predict(X_train)
        residuals_train = y_pred_train - y_train

        y_pred_test = regressor.predict(X_test)
        residuals_test = y_pred_test - y_test

        wandb.log(
            {
                "residuals": calculate.residuals(
                    y_pred_train,
                    residuals_train,
                    y_pred_test,
                    residuals_test,
                    train_score_,
                    test_score_,
                )
            }
        )
