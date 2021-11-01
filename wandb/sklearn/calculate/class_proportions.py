from warnings import simplefilter

import numpy as np

import wandb
from wandb.sklearn import utils

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def class_proportions(classes_, class_counts_train, class_counts_test, labels):
    class_dict = []
    dataset_dict = []
    count_dict = []
    for i in range(len(classes_)):
        # add class counts from training set
        class_dict.append(classes_[i])
        dataset_dict.append("train")
        count_dict.append(class_counts_train[i])
        # add class counts from test set
        class_dict.append(classes_[i])
        dataset_dict.append("test")
        count_dict.append(class_counts_test[i])
        if utils.check_against_limit(i, CHART_LIMIT, "class_proportions"):
            break

    if labels is not None and (
        isinstance(class_dict[0], int) or isinstance(class_dict[0], np.integer)
    ):
        class_dict = get_named_labels(labels, class_dict)
    return wandb.visualize(
        "wandb/class_proportions/v1",
        wandb.Table(
            columns=["class", "dataset", "count"],
            data=[
                [class_dict[i], dataset_dict[i], count_dict[i]]
                for i in range(len(class_dict))
            ],
        ),
    )


def get_named_labels(labels, numeric_labels):
    return np.array([labels[num_label] for num_label in numeric_labels])
