from __future__ import annotations

from typing import TYPE_CHECKING, Sequence, TypeVar

import wandb
from wandb import util
from wandb.plot.custom_chart import plot_table

if TYPE_CHECKING:
    from wandb.plot.custom_chart import CustomChart

T = TypeVar("T")


def confusion_matrix(
    probs: Sequence[Sequence[float]] | None = None,
    y_true: Sequence[T] | None = None,
    preds: Sequence[T] | None = None,
    class_names: Sequence[str] | None = None,
    title: str = "Confusion Matrix Curve",
    split_table: bool = False,
) -> CustomChart:
    """Constructs a confusion matrix from a sequence of probabilities or predictions.

    Args:
        probs (Sequence[Sequence[float]] | None): A sequence of predicted probabilities for each
            class. The sequence shape should be (N, K) where N is the number of samples
            and K is the number of classes. If provided, `preds` should not be provided.
        y_true (Sequence[T] | None): A sequence of true labels.
        preds (Sequence[T] | None): A sequence of predicted class labels. If provided,
            `probs` should not be provided.
        class_names (Sequence[str] | None): Sequence of class names. If not
            provided, class names will be defined as "Class_1", "Class_2", etc.
        title (str): Title of the confusion matrix chart.
        split_table (bool): Whether the table should be split into a separate section
            in the W&B UI. If `True`, the table will be displayed in a section named
            "Custom Chart Tables". Default is `False`.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass it to `wandb.log()`.

    Raises:
        ValueError: If both `probs` and `preds` are provided or if the number of
            predictions and true labels are not equal. If the number of unique
            predicted classes exceeds the number of class names or if the number of
            unique true labels exceeds the number of class names.
        wandb.Error: If numpy is not installed.

    Examples:
        1. Logging a confusion matrix with random probabilities for wildlife
        classification:
        ```
        import numpy as np
        import wandb

        # Define class names for wildlife
        wildlife_class_names = ["Lion", "Tiger", "Elephant", "Zebra"]

        # Generate random true labels (0 to 3 for 10 samples)
        wildlife_y_true = np.random.randint(0, 4, size=10)

       # Generate random probabilities for each class (10 samples x 4 classes)
        wildlife_probs = np.random.rand(10, 4)
        wildlife_probs = np.exp(wildlife_probs) / np.sum(
            np.exp(wildlife_probs),
            axis=1,
            keepdims=True,
        )

        # Initialize W&B run and log confusion matrix
        with wandb.init(project="wildlife_classification") as run:
            confusion_matrix = wandb.plot.confusion_matrix(
                    probs=wildlife_probs,
                    y_true=wildlife_y_true,
                    class_names=wildlife_class_names,
                    title="Wildlife Classification Confusion Matrix",
                )
            run.log({"wildlife_confusion_matrix": confusion_matrix})
        ```
        In this example, random probabilities are used to generate a confusion
        matrix.

        2. Logging a confusion matrix with simulated model predictions and 85%
        accuracy:
        ```
        import numpy as np
        import wandb

        # Define class names for wildlife
        wildlife_class_names = ["Lion", "Tiger", "Elephant", "Zebra"]

        # Simulate true labels for 200 animal images (imbalanced distribution)
        wildlife_y_true = np.random.choice(
            [0, 1, 2, 3],
            size=200,
            p=[0.2, 0.3, 0.25, 0.25],
        )

        # Simulate model predictions with 85% accuracy
        wildlife_preds = [
            y_t
            if np.random.rand() < 0.85
            else np.random.choice([x for x in range(4) if x != y_t])
            for y_t in wildlife_y_true
        ]

        # Initialize W&B run and log confusion matrix
        with wandb.init(project="wildlife_classification") as run:
            confusion_matrix = wandb.plot.confusion_matrix(
                preds=wildlife_preds,
                y_true=wildlife_y_true,
                class_names=wildlife_class_names,
                title="Simulated Wildlife Classification Confusion Matrix"
            )
            run.log({"wildlife_confusion_matrix": confusion_matrix})
        ```
        In this example, predictions are simulated with 85% accuracy to generate a
        confusion matrix.
    """
    np = util.get_module(
        "numpy",
        required=(
            "numpy is required to use wandb.plot.confusion_matrix, "
            "install with `pip install numpy`",
        ),
    )

    if probs is not None and preds is not None:
        raise ValueError("Only one of `probs` or `preds` should be provided, not both.")

    if probs is not None:
        preds = np.argmax(probs, axis=1).tolist()

    if len(preds) != len(y_true):
        raise ValueError("The number of predictions and true labels must be equal.")

    if class_names is not None:
        n_classes = len(class_names)
        class_idx = list(range(n_classes))
        if len(set(preds)) > len(class_names):
            raise ValueError(
                "The number of unique predicted classes exceeds the number of class names."
            )

        if len(set(y_true)) > len(class_names):
            raise ValueError(
                "The number of unique true labels exceeds the number of class names."
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

    return plot_table(
        data_table=wandb.Table(
            columns=["Actual", "Predicted", "nPredictions"],
            data=data,
        ),
        vega_spec_name="wandb/confusion_matrix/v1",
        fields={
            "Actual": "Actual",
            "Predicted": "Predicted",
            "nPredictions": "nPredictions",
        },
        string_fields={"title": title},
        split_table=split_table,
    )
