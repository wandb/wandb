from typing import Iterable, Optional, Sequence

import wandb
from wandb import util


def test_missing(**kwargs):
    np = util.get_module("numpy", required="Logging plots requires numpy")
    pd = util.get_module("pandas", required="Logging dataframes requires pandas")
    scipy = util.get_module("scipy", required="Logging scipy matrices requires scipy")

    test_passed = True
    for k, v in kwargs.items():
        # Missing/empty params/datapoint arrays
        if v is None:
            wandb.termerror("%s is None. Please try again." % (k))
            test_passed = False
        if (k == "X") or (k == "X_test"):
            if isinstance(v, scipy.sparse.csr.csr_matrix):
                v = v.toarray()
            elif isinstance(v, (pd.DataFrame, pd.Series)):
                v = v.to_numpy()
            elif isinstance(v, list):
                v = np.asarray(v)

            # Warn the user about missing values
            missing = 0
            missing = np.count_nonzero(pd.isnull(v))
            if missing > 0:
                wandb.termwarn("%s contains %d missing values. " % (k, missing))
                test_passed = False
            # Ensure the dataset contains only integers
            non_nums = 0
            if v.ndim == 1:
                non_nums = sum(
                    1
                    for val in v
                    if (
                        not isinstance(val, (int, float, complex))
                        and not isinstance(val, np.number)
                    )
                )
            else:
                non_nums = sum(
                    1
                    for sl in v
                    for val in sl
                    if (
                        not isinstance(val, (int, float, complex))
                        and not isinstance(val, np.number)
                    )
                )
            if non_nums > 0:
                wandb.termerror(
                    "%s contains values that are not numbers. Please vectorize, label encode or one hot encode %s and call the plotting function again."
                    % (k, k)
                )
                test_passed = False
    return test_passed


def test_fitted(model):
    np = util.get_module("numpy", required="Logging plots requires numpy")
    pd = util.get_module("pandas", required="Logging dataframes requires pandas")
    scipy = util.get_module("scipy", required="Logging scipy matrices requires scipy")
    scikit_utils = util.get_module(
        "sklearn.utils",
        required="roc requires the scikit utils submodule, install with `pip install scikit-learn`",
    )
    scikit_exceptions = util.get_module(
        "sklearn.exceptions",
        "roc requires the scikit preprocessing submodule, install with `pip install scikit-learn`",
    )

    try:
        model.predict(np.zeros((7, 3)))
    except scikit_exceptions.NotFittedError:
        wandb.termerror("Please fit the model before passing it in.")
        return False
    except AttributeError:
        # Some clustering models (LDA, PCA, Agglomerative) don't implement ``predict``
        try:
            scikit_utils.validation.check_is_fitted(
                model,
                [
                    "coef_",
                    "estimator_",
                    "labels_",
                    "n_clusters_",
                    "children_",
                    "components_",
                    "n_components_",
                    "n_iter_",
                    "n_batch_iter_",
                    "explained_variance_",
                    "singular_values_",
                    "mean_",
                ],
                all_or_any=any,
            )
            return True
        except scikit_exceptions.NotFittedError:
            wandb.termerror("Please fit the model before passing it in.")
            return False
    except Exception:
        # Assume it's fitted, since ``NotFittedError`` wasn't raised
        return True


def encode_labels(df):
    pd = util.get_module("pandas", required="Logging dataframes requires pandas")
    preprocessing = util.get_module(
        "sklearn.preprocessing",
        "roc requires the scikit preprocessing submodule, install with `pip install scikit-learn`",
    )

    le = preprocessing.LabelEncoder()
    # apply le on categorical feature columns
    categorical_cols = df.select_dtypes(
        exclude=["int", "float", "float64", "float32", "int32", "int64"]
    ).columns
    df[categorical_cols] = df[categorical_cols].apply(lambda col: le.fit_transform(col))


def test_types(**kwargs):
    np = util.get_module("numpy", required="Logging plots requires numpy")
    pd = util.get_module("pandas", required="Logging dataframes requires pandas")
    scipy = util.get_module("scipy", required="Logging scipy matrices requires scipy")

    base = util.get_module(
        "sklearn.base",
        "roc requires the scikit base submodule, install with `pip install scikit-learn`",
    )

    test_passed = True
    for k, v in kwargs.items():
        # check for incorrect types
        if (
            (k == "X")
            or (k == "X_test")
            or (k == "y")
            or (k == "y_test")
            or (k == "y_true")
            or (k == "y_probas")
            or (k == "x_labels")
            or (k == "y_labels")
            or (k == "matrix_values")
        ):
            # FIXME: do this individually
            if not isinstance(
                v,
                (
                    Sequence,
                    Iterable,
                    np.ndarray,
                    np.generic,
                    pd.DataFrame,
                    pd.Series,
                    list,
                ),
            ):
                wandb.termerror("%s is not an array. Please try again." % (k))
                test_passed = False
        # check for classifier types
        if k == "model":
            if (not base.is_classifier(v)) and (not base.is_regressor(v)):
                wandb.termerror(
                    "%s is not a classifier or regressor. Please try again." % (k)
                )
                test_passed = False
        elif k == "clf" or k == "binary_clf":
            if not (base.is_classifier(v)):
                wandb.termerror("%s is not a classifier. Please try again." % (k))
                test_passed = False
        elif k == "regressor":
            if not base.is_regressor(v):
                wandb.termerror("%s is not a regressor. Please try again." % (k))
                test_passed = False
        elif k == "clusterer":
            if not (getattr(v, "_estimator_type", None) == "clusterer"):
                wandb.termerror("%s is not a clusterer. Please try again." % (k))
                test_passed = False
    return test_passed


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
