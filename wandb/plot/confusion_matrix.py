import wandb
from wandb import util

chart_limit = wandb.Table.MAX_ROWS


def confusion_matrix(preds=None, y_true=None, class_names=None):
    """
    Computes a multi-run confusion matrix.

    Arguments:
    preds (arr): Array of predicted label indices.
    y_true (arr): Array of label indices.
    class_names (arr): Array of class names.

    Returns:
    Nothing. To see plots, go to your W&B run page then expand the 'media' tab
    under 'auto visualizations'.

    Example:
    wandb.log({'pr': wandb.plot.confusion_matrix(preds, y_true, labels)})
    """

    np = util.get_module(
        "numpy",
        required="confusion matrix requires the numpy library, install with `pip install numpy`",
    )
    assert len(preds) == len(
        y_true
    ), "Number of predictions and label indices must match"
    if class_names is not None:
        n_classes = len(class_names)
        assert max(preds) <= len(
            class_names
        ), "Higher predicted index than number of classes"
        assert max(y_true) <= len(
            class_names
        ), "Higher label class index than number of classes"
    else:
        n_classes = max(max(preds), max(y_true))
        class_names = ["Class_{}".format(i) for i in range(1, n_classes + 1)]

    counts = np.zeros((n_classes, n_classes))
    for i in range(len(preds)):
        counts[y_true[i], preds[i]] += 1

    data = []
    for i in range(n_classes):
        for j in range(n_classes):
            data.append([class_names[i], class_names[j], counts[i, j]])

    fields = {"Actual": "Actual", "Predicted": "Predicted", "nPredicted": "Count"}

    return wandb.plot_table(
        "wandb/confusion_matrix/v0",
        wandb.Table(columns=["Actual", "Predicted", "Count"], data=data),
        fields,
    )
