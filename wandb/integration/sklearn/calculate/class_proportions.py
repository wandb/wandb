from warnings import simplefilter

import numpy as np
from sklearn.utils.multiclass import unique_labels

import wandb
from wandb.integration.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def class_proportions(y_train, y_test, labels):
    # Get the unique values from the dataset
    targets = (y_train,) if y_test is None else (y_train, y_test)
    class_ids = np.array(unique_labels(*targets))

    # Compute the class counts
    counts_train = np.array([(y_train == c).sum() for c in class_ids])
    counts_test = np.array([(y_test == c).sum() for c in class_ids])

    class_column, dataset_column, count_column = make_columns(
        class_ids, counts_train, counts_test
    )

    if labels is not None and (
        isinstance(class_column[0], int) or isinstance(class_column[0], np.integer)
    ):
        class_column = get_named_labels(labels, class_column)

    table = make_table(class_column, dataset_column, count_column)
    chart = wandb.visualize("wandb/class_proportions/v1", table)

    return chart


def make_table(class_column, dataset_column, count_column):
    columns = ["class", "dataset", "count"]
    data = list(zip(class_column, dataset_column, count_column))

    return wandb.Table(data=data, columns=columns)


def make_columns(class_ids, counts_train, counts_test):
    class_column, dataset_column, count_column = [], [], []

    for i in range(len(class_ids)):
        # add class counts from training set
        class_column.append(class_ids[i])
        dataset_column.append("train")
        count_column.append(counts_train[i])
        # add class counts from test set
        class_column.append(class_ids[i])
        dataset_column.append("test")
        count_column.append(counts_test[i])

        if utils.check_against_limit(
            i,
            "class_proportions",
            utils.chart_limit,
        ):
            break

    return class_column, dataset_column, count_column


def get_named_labels(labels, numeric_labels):
    return np.array([labels[num_label] for num_label in numeric_labels])
