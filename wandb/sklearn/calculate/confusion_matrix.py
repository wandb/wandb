import itertools
from warnings import simplefilter

import numpy as np
from sklearn import metrics
from sklearn.utils.multiclass import unique_labels

import wandb
from wandb.sklearn import utils

from fakemodule import validate_labels  # TODO: fix

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)

CHART_LIMIT = 1000


def confusion_matrix(
    y_true=None,
    y_pred=None,
    labels=None,
    true_labels=None,
    pred_labels=None,
    title=None,
    normalize=False,
    hide_zeros=False,
    hide_counts=False,
):
    """Computes the confusion matrix to evaluate the performance of a classification.

    Called by plot_confusion_matrix to visualize roc curves. Please use the function
    plot_confusion_matrix() if you wish to visualize your confusion matrix.
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    if utils.test_missing(y_true=y_true, y_pred=y_pred) and utils.test_types(
        y_true=y_true, y_pred=y_pred
    ):
        cm = metrics.confusion_matrix(y_true, y_pred)
        if labels is None:
            classes = unique_labels(y_true, y_pred)
        else:
            classes = np.asarray(labels)

        if normalize:
            cm = cm.astype("float") / cm.sum(axis=1)[:, np.newaxis]
            cm = np.around(cm, decimals=2)
            cm[np.isnan(cm)] = 0.0

        if true_labels is None:
            true_classes = classes
        else:
            validate_labels(classes, true_labels, "true_labels")

            true_label_indexes = np.in1d(classes, true_labels)

            true_classes = classes[true_label_indexes]
            cm = cm[true_label_indexes]

        if pred_labels is None:
            pred_classes = classes
        else:
            validate_labels(classes, pred_labels, "pred_labels")

            pred_label_indexes = np.in1d(classes, pred_labels)

            pred_classes = classes[pred_label_indexes]
            cm = cm[:, pred_label_indexes]

        return make_confusion_matrix_table(cm, pred_classes, true_classes, labels)


def make_confusion_matrix_table(cm, pred_classes, true_classes, labels):
    data, count = [], 0
    for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
        if labels is not None and (
            isinstance(pred_classes[i], int) or isinstance(pred_classes[0], np.integer)
        ):
            pred_dict = labels[pred_classes[i]]
            true_dict = labels[true_classes[j]]
        else:
            pred_dict = pred_classes[i]
            true_dict = true_classes[j]
        data.append([pred_dict, true_dict, cm[i, j]])
        count += 1
        if utils.check_against_limit(count, CHART_LIMIT, "confusion_matrix"):
            break
    return wandb.visualize(
        "wandb/confusion_matrix/v1",
        wandb.Table(columns=["Predicted", "Actual", "Count"], data=data),
    )
