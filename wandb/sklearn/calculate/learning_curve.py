from warnings import simplefilter

import numpy as np
from sklearn import model_selection

import wandb
from wandb.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def learning_curve(
    model,
    X,
    y,
    cv=None,
    shuffle=False,
    random_state=None,
    train_sizes=None,
    n_jobs=1,
    scoring=None,
):
    """Trains model on datasets of varying size and generates plot of score vs size.

    Called by plot_learning_curve to visualize learning curve. Please use the function
    plot_learning_curve() if you wish to visualize your learning curves.
    """
    if train_sizes is None:
        train_sizes = np.linspace(0.1, 1.0, 5)
    if utils.test_missing(model=model, X=X, y=y) and utils.test_types(
        model=model, X=X, y=y
    ):
        y = np.asarray(y)
        train_sizes, train_scores, test_scores = model_selection.learning_curve(
            model,
            X,
            y,
            cv=cv,
            n_jobs=n_jobs,
            train_sizes=train_sizes,
            scoring=scoring,
            shuffle=shuffle,
            random_state=random_state,
        )
        train_scores_mean = np.mean(train_scores, axis=1)
        test_scores_mean = np.mean(test_scores, axis=1)

        return make_learning_curve_table(
            train_scores_mean, test_scores_mean, train_sizes
        )


def make_learning_curve_table(train, test, trainsize):
    data = []
    for i in range(len(train)):
        if utils.check_against_limit(i, CHART_LIMIT / 2, "learning_curve"):
            break
        train_set = ["train", round(train[i], 2), trainsize[i]]
        test_set = ["test", round(test[i], 2), trainsize[i]]
        data.append(train_set)
        data.append(test_set)
    return wandb.visualize(
        "wandb/learning_curve/v1",
        wandb.Table(columns=["dataset", "score", "train_size"], data=data),
    )
