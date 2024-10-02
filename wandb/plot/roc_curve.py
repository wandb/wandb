from typing import Optional

import wandb
from wandb import util

from .utils import test_missing, test_types


def roc_curve(
    y_true=None,
    y_probas=None,
    labels=None,
    classes_to_plot=None,
    title=None,
    split_table: Optional[bool] = False,
):
    """Calculate and visualize receiver operating characteristic (ROC) scores.

    Arguments:
        y_true (arr): true sparse labels
        y_probas (arr): Target scores, can either be probability estimates, confidence
                         values, or non-thresholded measure of decisions.
                         shape: (*y_true.shape, num_classes)
        labels (list): Named labels for target variable (y). Makes plots easier to
                        read by replacing target values with corresponding index.
                        For example labels = ['dog', 'cat', 'owl'] all 0s are
                        replaced by 'dog', 1s by 'cat'.
        classes_to_plot (list): unique values of y_true to include in the plot
        split_table (bool): If True, adds "Custom Chart Tables/" to the key of the table so that it's logged in a different section.

    Returns:
        Nothing. To see plots, go to your W&B run page then expand the 'media' tab
            under 'auto visualizations'.

    Example:
        ```
        wandb.log({'roc-curve': wandb.plot.roc_curve(y_true, y_probas, labels)})
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

    y_true = np.array(y_true)
    y_probas = np.array(y_probas)

    if not test_missing(y_true=y_true, y_probas=y_probas):
        return
    if not test_types(y_true=y_true, y_probas=y_probas):
        return

    classes = np.unique(y_true)
    if classes_to_plot is None:
        classes_to_plot = classes

    fpr = dict()
    tpr = dict()
    indices_to_plot = np.where(np.isin(classes, classes_to_plot))[0]
    for i in indices_to_plot:
        if labels is not None and (
            isinstance(classes[i], int) or isinstance(classes[0], np.integer)
        ):
            class_label = labels[classes[i]]
        else:
            class_label = classes[i]

        fpr[class_label], tpr[class_label], _ = sklearn_metrics.roc_curve(
            y_true, y_probas[..., i], pos_label=classes[i]
        )

    df = pd.DataFrame(
        {
            "class": np.hstack([[k] * len(v) for k, v in fpr.items()]),
            "fpr": np.hstack(list(fpr.values())),
            "tpr": np.hstack(list(tpr.values())),
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
        ).sort_values(["fpr", "tpr", "class"])

    table = wandb.Table(dataframe=df)
    title = title or "ROC"
    return wandb.plot_table(
        "wandb/area-under-curve/v0",
        table,
        {"x": "fpr", "y": "tpr", "class": "class"},
        {
            "title": title,
            "x-axis-title": "False positive rate",
            "y-axis-title": "True positive rate",
        },
        split_table=split_table,
    )
