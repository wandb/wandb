from __future__ import annotations

import numbers
from typing import TYPE_CHECKING, Iterable, TypeVar

import wandb
from wandb import util
from wandb.plot.custom_chart import plot_table
from wandb.plot.utils import test_missing, test_types

if TYPE_CHECKING:
    from wandb.plot.custom_chart import CustomChart


T = TypeVar("T")


def pr_curve(
    y_true: Iterable[T] | None = None,
    y_probas: Iterable[numbers.Number] | None = None,
    labels: list[str] | None = None,
    classes_to_plot: list[T] | None = None,
    interp_size: int = 21,
    title: str = "Precision-Recall Curve",
    split_table: bool = False,
) -> CustomChart:
    """Constructs a Precision-Recall (PR) curve.

    The Precision-Recall curve is particularly useful for evaluating classifiers
    on imbalanced datasets. A high area under the PR curve signifies both high
    precision (a low false positive rate) and high recall (a low false negative
    rate). The curve provides insights into the balance between false positives
    and false negatives at various threshold levels, aiding in the assessment of
    a model's performance.

    Args:
        y_true (Iterable): True binary labels. The shape should be (`num_samples`,).
        y_probas (Iterable): Predicted scores or probabilities for each class.
            These can be probability estimates, confidence scores, or non-thresholded
            decision values. The shape should be (`num_samples`, `num_classes`).
        labels (list[str] | None): Optional list of class names to replace
            numeric values in `y_true` for easier plot interpretation.
            For example, `labels = ['dog', 'cat', 'owl']` will replace 0 with
            'dog', 1 with 'cat', and 2 with 'owl' in the plot. If not provided,
            numeric values from `y_true` will be used.
        classes_to_plot (list | None): Optional list of unique class values from
            y_true to be included in the plot. If not specified, all unique
            classes in y_true will be plotted.
        interp_size (int): Number of points to interpolate recall values. The
            recall values will be fixed to `interp_size` uniformly distributed
            points in the range [0, 1], and the precision will be interpolated
            accordingly.
        title (str): Title of the plot. Defaults to "Precision-Recall Curve".
        split_table (bool): Whether the table should be split into a separate section
            in the W&B UI. If `True`, the table will be displayed in a section named
            "Custom Chart Tables". Default is `False`.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass it to `wandb.log()`.

    Raises:
        wandb.Error: If numpy, pandas, or scikit-learn is not installed.


    Example:
        ```
        import wandb

        # Example for spam detection (binary classification)
        y_true = [0, 1, 1, 0, 1]  # 0 = not spam, 1 = spam
        y_probas = [
            [0.9, 0.1],  # Predicted probabilities for the first sample (not spam)
            [0.2, 0.8],  # Second sample (spam), and so on
            [0.1, 0.9],
            [0.8, 0.2],
            [0.3, 0.7],
        ]

        labels = ["not spam", "spam"]  # Optional class names for readability

        with wandb.init(project="spam-detection") as run:
            pr_curve = wandb.plot.pr_curve(
                y_true=y_true,
                y_probas=y_probas,
                labels=labels,
                title="Precision-Recall Curve for Spam Detection",
            )
            run.log({"pr-curve": pr_curve})
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

    precision = {}
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
    ).round(3)

    if len(df) > wandb.Table.MAX_ROWS:
        wandb.termwarn(
            f"Table has a limit of {wandb.Table.MAX_ROWS} rows. Resampling to fit."
        )
        # different sampling could be applied, possibly to ensure endpoints are kept
        df = sklearn_utils.resample(
            df,
            replace=False,
            n_samples=wandb.Table.MAX_ROWS,
            random_state=42,
            stratify=df["class"],
        ).sort_values(["precision", "recall", "class"])

    return plot_table(
        data_table=wandb.Table(dataframe=df),
        vega_spec_name="wandb/area-under-curve/v0",
        fields={
            "x": "recall",
            "y": "precision",
            "class": "class",
        },
        string_fields={
            "title": title,
            "x-axis-title": "Recall",
            "y-axis-title": "Precision",
        },
        split_table=split_table,
    )
