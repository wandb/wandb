from typing import Optional

import wandb
from wandb import util

from .utils import test_missing, test_types


def pr_curve(
    y_true=None,
    y_probas=None,
    labels=None,
    classes_to_plot=None,
    interp_size=21,
    title=None,
    split_table: Optional[bool] = False,
):
    """Compute the tradeoff between precision and recall for different thresholds.

    A high area under the curve represents both high recall and high precision, where
    high precision relates to a low false positive rate, and high recall relates to a
    low false negative rate. High scores for both show that the classifier is returning
    accurate results (high precision), and returning a majority of all positive results
    (high recall). PR curve is useful when the classes are very imbalanced.

    Arguments:
        y_true (arr): true sparse labels y_probas (arr): Target scores, can either be
            probability estimates, confidence values, or non-thresholded measure of
            decisions. shape: (*y_true.shape, num_classes)
        labels (list): Named labels for target variable (y). Makes plots easier to read
            by replacing target values with corresponding index. For example labels =
            ['dog', 'cat', 'owl'] all 0s are replaced by 'dog', 1s by 'cat'.
        classes_to_plot (list): unique values of y_true to include in the plot
        interp_size (int): the recall values will be fixed to `interp_size` points
            uniform on [0, 1] and the precision will be interpolated for these recall
            values.
        split_table (bool): If True, adds "Custom Chart Tables/" to the key of the table so that it's logged in a different section.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab under
        'auto visualizations'.

    Example:
        ```
        wandb.log({"pr-curve": wandb.plot.pr_curve(y_true, y_probas, labels)})
        ```
    """
    np = util.get_module(
        "numpy",
        required="roc requires the numpy library, install with `pip install numpy`",
    )
    pd = util.get_module(
        "pandas",
        required="roc requires the pandas library, install with `pip install pandas`",
    )
    sklearn_metrics = util.get_module(
        "sklearn.metrics",
        "roc requires the scikit library, install with `pip install scikit-learn`",
    )
    sklearn_utils = util.get_module(
        "sklearn.utils",
        "roc requires the scikit library, install with `pip install scikit-learn`",
    )

    def _step(x):
        y = np.array(x)
        for i in range(1, len(y)):
            y[i] = max(y[i], y[i - 1])
        return y

    y_true = np.array(y_true)
    y_probas = np.array(y_probas)

    if not test_missing(y_true=y_true, y_probas=y_probas):
        return
    if not test_types(y_true=y_true, y_probas=y_probas):
        return

    classes = np.unique(y_true)
    if classes_to_plot is None:
        classes_to_plot = classes

    precision = dict()
    interp_recall = np.linspace(0, 1, interp_size)[::-1]
    indices_to_plot = np.where(np.isin(classes, classes_to_plot))[0]
    for i in indices_to_plot:
        if labels is not None and (
            isinstance(classes[i], int) or isinstance(classes[0], np.integer)
        ):
            class_label = labels[classes[i]]
        else:
            class_label = classes[i]

        cur_precision, cur_recall, _ = sklearn_metrics.precision_recall_curve(
            y_true, y_probas[:, i], pos_label=classes[i]
        )
        # smooth the precision (monotonically increasing)
        cur_precision = _step(cur_precision)

        # reverse order so that recall in ascending
        cur_precision = cur_precision[::-1]
        cur_recall = cur_recall[::-1]
        indices = np.searchsorted(cur_recall, interp_recall, side="left")
        precision[class_label] = cur_precision[indices]

    df = pd.DataFrame(
        {
            "class": np.hstack([[k] * len(v) for k, v in precision.items()]),
            "precision": np.hstack(list(precision.values())),
            "recall": np.tile(interp_recall, len(precision)),
        }
    )
    df = df.round(3)

    if len(df) > wandb.Table.MAX_ROWS:
        wandb.termwarn(
            "wandb uses only %d data points to create the plots." % wandb.Table.MAX_ROWS
        )
        # different sampling could be applied, possibly to ensure endpoints are kept
        df = sklearn_utils.resample(
            df,
            replace=False,
            n_samples=wandb.Table.MAX_ROWS,
            random_state=42,
            stratify=df["class"],
        ).sort_values(["precision", "recall", "class"])

    table = wandb.Table(dataframe=df)
    title = title or "Precision v. Recall"
    return wandb.plot_table(
        "wandb/area-under-curve/v0",
        table,
        {"x": "recall", "y": "precision", "class": "class"},
        {"title": title},
        split_table=split_table,
    )
