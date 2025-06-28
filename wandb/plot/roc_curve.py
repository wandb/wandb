from __future__ import annotations

import numbers
from typing import TYPE_CHECKING, Sequence

import wandb
from wandb import util
from wandb.plot.custom_chart import plot_table
from wandb.plot.utils import test_missing, test_types

if TYPE_CHECKING:
    from wandb.plot.custom_chart import CustomChart


def roc_curve(
    y_true: Sequence[numbers.Number],
    y_probas: Sequence[Sequence[float]] | None = None,
    labels: list[str] | None = None,
    classes_to_plot: list[numbers.Number] | None = None,
    title: str = "ROC Curve",
    split_table: bool = False,
) -> CustomChart:
    """Constructs Receiver Operating Characteristic (ROC) curve chart.

    Args:
        y_true: The true class labels (ground truth)
            for the target variable. Shape should be (num_samples,).
        y_probas: The predicted probabilities or
            decision scores for each class. Shape should be (num_samples, num_classes).
        labels: Human-readable labels corresponding to the class
            indices in `y_true`. For example, if `labels=['dog', 'cat']`,
            class 0 will be displayed as 'dog' and class 1 as 'cat' in the plot.
            If None, the raw class indices from `y_true` will be used.
            Default is None.
        classes_to_plot: A subset of unique class labels
            to include in the ROC curve. If None, all classes in `y_true` will
            be plotted. Default is None.
        title: Title of the ROC curve plot. Default is "ROC Curve".
        split_table: Whether the table should be split into a separate
            section in the W&B UI. If `True`, the table will be displayed in a
            section named "Custom Chart Tables". Default is `False`.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass it to `wandb.log()`.

    Raises:
        wandb.Error: If numpy, pandas, or scikit-learn are not found.

    Example:
    ```python
    import numpy as np
    import wandb

    # Simulate a medical diagnosis classification problem with three diseases
    n_samples = 200
    n_classes = 3

    # True labels: assign "Diabetes", "Hypertension", or "Heart Disease" to
    # each sample
    disease_labels = ["Diabetes", "Hypertension", "Heart Disease"]
    # 0: Diabetes, 1: Hypertension, 2: Heart Disease
    y_true = np.random.choice([0, 1, 2], size=n_samples)

    # Predicted probabilities: simulate predictions, ensuring they sum to 1
    # for each sample
    y_probas = np.random.dirichlet(np.ones(n_classes), size=n_samples)

    # Specify classes to plot (plotting all three diseases)
    classes_to_plot = [0, 1, 2]

    # Initialize a W&B run and log a ROC curve plot for disease classification
    with wandb.init(project="medical_diagnosis") as run:
        roc_plot = wandb.plot.roc_curve(
            y_true=y_true,
            y_probas=y_probas,
            labels=disease_labels,
            classes_to_plot=classes_to_plot,
            title="ROC Curve for Disease Classification",
        )
        run.log({"roc-curve": roc_plot})
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

    fpr = {}
    tpr = {}
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
    ).round(3)

    if len(df) > wandb.Table.MAX_ROWS:
        wandb.termwarn(
            f"wandb uses only {wandb.Table.MAX_ROWS} data points to create the plots."
        )
        # different sampling could be applied, possibly to ensure endpoints are kept
        df = sklearn_utils.resample(
            df,
            replace=False,
            n_samples=wandb.Table.MAX_ROWS,
            random_state=42,
            stratify=df["class"],
        ).sort_values(["fpr", "tpr", "class"])

    return plot_table(
        data_table=wandb.Table(dataframe=df),
        vega_spec_name="wandb/area-under-curve/v0",
        fields={
            "x": "fpr",
            "y": "tpr",
            "class": "class",
        },
        string_fields={
            "title": title,
            "x-axis-title": "False positive rate",
            "y-axis-title": "True positive rate",
        },
        split_table=split_table,
    )
