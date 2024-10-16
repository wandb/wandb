from __future__ import annotations

from typing import Sequence

from wandb import util
from wandb.data_types import Table
from wandb.plot.viz import CustomChart


def confusion_matrix(
    probs: Sequence[Sequence] | None = None,
    y_true: Sequence | None = None,
    preds: Sequence | None = None,
    class_names: Sequence[str] | None = None,
    title: str | None = None,
    split_table: bool | None = False,
) -> CustomChart:
    """Computes a multi-run confusion matrix.

    Args:
        probs (Sequence[Sequence]): Array of probabilities, shape (N, K) where N is the number
            of samples and K is the number of classes.
        y_true (Sequence): Sequence of true label indices.
        preds (Sequence): Sequence of predicted label indices.
        class_names (Sequence[str]): Sequence of class names. If not provided, class names
            will be defined as "Class_1", "Class_2", etc.
        title (str): Title of the confusion matrix.
        split_table (bool): Whether to split the table into a different section
            in the UI. Default is False.

    Returns:
        CustomChart: A confusion matrix chart. That can be logged to W&B with
            `wandb.log({'confusion_matrix': confusion_matrix})`.

    Example:
        ```
        import numpy as np
        import wandb

        # Generate random values and calculate probabilities
        values = np.random.uniform(size=(10, 5))
        probs = np.exp(values) / np.sum(np.exp(values), keepdims=True, axis=1)

        # Generate random true labels and define class names
        y_true = np.random.randint(0, 5, size=(10))
        labels = ["Cat", "Dog", "Bird", "Fish", "Horse"]

        # Log confusion matrix to wandb
        with wandb.init(...) as run:
            confusion_matrix = wandb.plot.confusion_matrix(
                    probs=probs,
                    y_true=y_true,
                    class_names=labels,
                    title="Confusion Matrix",
                )
            run.log({"confusion_matrix": confusion_matrix)})
        ```
    """
    np = util.get_module(
        "numpy",
        required=(
            "numpy is required to use wandb.plot.confusion_matrix, "
            "install with `pip install numpy`",
        ),
    )

    if probs is not None and len(probs.shape) != 2:
        raise ValueError(
            "confusion_matrix has been updated to accept"
            " probabilities as the default first argument. Use preds=..."
        )

    if probs is not None and preds is not None:
        raise ValueError(
            "confusion_matrix accepts either probabilities or predictions as input,"
            "not both"
        )

    if probs is not None:
        preds = np.argmax(probs, axis=1).tolist()

    if len(preds) != len(y_true):
        raise ValueError("Number of predictions and label indices must match")

    if class_names is not None:
        n_classes = len(class_names)
        class_idx = list(range(n_classes))
        if max(preds) > len(class_names):
            raise ValueError(
                "The maximal predicted index is greater than the number of classes"
            )

        if max(y_true) > len(class_names):
            raise ValueError(
                "The maximal label class index is greater than the number of classes"
            )
    else:
        class_idx = set(preds).union(set(y_true))
        n_classes = len(class_idx)
        class_names = [f"Class_{i+1}" for i in range(n_classes)]

    # Create a mapping from class name to index
    class_mapping = {val: i for i, val in enumerate(sorted(list(class_idx)))}

    counts = np.zeros((n_classes, n_classes))
    for i in range(len(preds)):
        counts[class_mapping[y_true[i]], class_mapping[preds[i]]] += 1

    data = [
        [class_names[i], class_names[j], counts[i, j]]
        for i in range(n_classes)
        for j in range(n_classes)
    ]

    return CustomChart(
        id="wandb/confusion_matrix/v1",
        data=Table(
            columns=["Actual", "Predicted", "nPredictions"],
            data=data,
        ),
        fields={
            "Actual": "Actual",
            "Predicted": "Predicted",
            "nPredictions": "nPredictions",
        },
        string_fields={"title": title or ""},
        split_table=split_table,
    )
