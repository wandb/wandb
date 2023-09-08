from warnings import simplefilter

import numpy as np
from sklearn import model_selection

import wandb
from wandb.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


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
    """Train model on datasets of varying size and generates plot of score vs size.

    Called by plot_learning_curve to visualize learning curve. Please use the function
    plot_learning_curve() if you wish to visualize your learning curves.
    """
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

    table = make_table(train_scores_mean, test_scores_mean, train_sizes)
    chart = wandb.visualize("wandb/learning_curve/v1", table)

    return chart


def make_table(train, test, train_sizes):
    data = []
    for i in range(len(train)):
        if utils.check_against_limit(
            i,
            "learning_curve",
            utils.chart_limit / 2,
        ):
            break
        train_set = ["train", utils.round_2(train[i]), train_sizes[i]]
        test_set = ["test", utils.round_2(test[i]), train_sizes[i]]
        data.append(train_set)
        data.append(test_set)

    table = wandb.Table(columns=["dataset", "score", "train_size"], data=data)
    return table
