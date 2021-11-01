"""Logs sklearn model plots to W&B."""
from warnings import simplefilter

import wandb

from wandb.sklearn import calculate

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def summary_metrics(model=None, X=None, y=None, X_test=None, y_test=None):
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
        wandb.sklearn.plot_summary_metrics(model, X_train, y_train, X_test, y_test)
    """
    wandb.log(
        {"summary_metrics": calculate.summary_metrics(model, X, y, X_test, y_test)}
    )


def learning_curve(
    model=None,
    X=None,
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

    Returns:
        None: To see plots, go to your W&B run page then expand the 'media' tab
              under 'auto visualizations'.

    Example:
    ```python
        wandb.sklearn.plot_learning_curve(model, X, y)
    ```
    """
    wandb.log(
        {
            "learning_curve": calculate.learning_curve(
                model, X, y, cv, shuffle, random_state, train_sizes, n_jobs, scoring
            )
        }
    )
