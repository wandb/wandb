from typing import Optional, Sequence

import wandb
from wandb import util

chart_limit = wandb.Table.MAX_ROWS


def confusion_matrix(
    probs: Optional[Sequence[Sequence]] = None,
    y_true: Optional[Sequence] = None,
    preds: Optional[Sequence] = None,
    class_names: Optional[Sequence[str]] = None,
    title: Optional[str] = None,
    split_table: Optional[bool] = False,
):
    """Compute a multi-run confusion matrix.

    Arguments:
        probs (2-d arr): Shape [n_examples, n_classes]
        y_true (arr): Array of label indices.
        preds (arr): Array of predicted label indices.
        class_names (arr): Array of class names.
        split_table (bool): If True, adds "Custom Chart Tables/" to the key of the table so that it's logged in a different section.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
        under 'auto visualizations'.

    Example:
        ```
        vals = np.random.uniform(size=(10, 5))
        probs = np.exp(vals)/np.sum(np.exp(vals), keepdims=True, axis=1)
        y_true = np.random.randint(0, 5, size=(10))
        labels = ["Cat", "Dog", "Bird", "Fish", "Horse"]
        wandb.log({'confusion_matrix': wandb.plot.confusion_matrix(probs, y_true=y_true, class_names=labels)})
        ```
    """
    np = util.get_module(
        "numpy",
        required="confusion matrix requires the numpy library, install with `pip install numpy`",
    )
    # change warning
    assert probs is None or len(probs.shape) == 2, (
        "confusion_matrix has been updated to accept"
        " probabilities as the default first argument. Use preds=..."
    )

    assert (probs is None or preds is None) and not (
        probs is None and preds is None
    ), "Must provide probabilities or predictions but not both to confusion matrix"

    if probs is not None:
        preds = np.argmax(probs, axis=1).tolist()

    assert len(preds) == len(
        y_true
    ), "Number of predictions and label indices must match"

    if class_names is not None:
        n_classes = len(class_names)
        class_inds = [i for i in range(n_classes)]
        assert max(preds) <= len(
            class_names
        ), "Higher predicted index than number of classes"
        assert max(y_true) <= len(
            class_names
        ), "Higher label class index than number of classes"
    else:
        class_inds = set(preds).union(set(y_true))
        n_classes = len(class_inds)
        class_names = [f"Class_{i}" for i in range(1, n_classes + 1)]

    # get mapping of inds to class index in case user has weird prediction indices
    class_mapping = {}
    for i, val in enumerate(sorted(list(class_inds))):
        class_mapping[val] = i
    counts = np.zeros((n_classes, n_classes))
    for i in range(len(preds)):
        counts[class_mapping[y_true[i]], class_mapping[preds[i]]] += 1

    data = []
    for i in range(n_classes):
        for j in range(n_classes):
            data.append([class_names[i], class_names[j], counts[i, j]])

    fields = {
        "Actual": "Actual",
        "Predicted": "Predicted",
        "nPredictions": "nPredictions",
    }
    title = title or ""
    return wandb.plot_table(
        "wandb/confusion_matrix/v1",
        wandb.Table(columns=["Actual", "Predicted", "nPredictions"], data=data),
        fields,
        {"title": title},
        split_table=split_table,
    )
