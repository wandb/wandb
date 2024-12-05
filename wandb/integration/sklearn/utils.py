"""Shared utilities for the modules in wandb.sklearn."""

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd
import scipy
import sklearn

import wandb

chart_limit = 1000


def check_against_limit(count, chart, limit=None):
    if limit is None:
        limit = chart_limit
    if count > limit:
        warn_chart_limit(limit, chart)
        return True
    else:
        return False


def warn_chart_limit(limit, chart):
    warning = f"using only the first {limit} datapoints to create chart {chart}"
    wandb.termwarn(warning)


def encode_labels(df):
    le = sklearn.preprocessing.LabelEncoder()
    # apply le on categorical feature columns
    categorical_cols = df.select_dtypes(
        exclude=["int", "float", "float64", "float32", "int32", "int64"]
    ).columns
    df[categorical_cols] = df[categorical_cols].apply(lambda col: le.fit_transform(col))


def test_types(**kwargs):
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
                wandb.termerror(f"{k} is not an array. Please try again.")
                test_passed = False
        # check for classifier types
        if k == "model":
            if (not sklearn.base.is_classifier(v)) and (
                not sklearn.base.is_regressor(v)
            ):
                wandb.termerror(
                    f"{k} is not a classifier or regressor. Please try again."
                )
                test_passed = False
        elif k == "clf" or k == "binary_clf":
            if not (sklearn.base.is_classifier(v)):
                wandb.termerror(f"{k} is not a classifier. Please try again.")
                test_passed = False
        elif k == "regressor":
            if not sklearn.base.is_regressor(v):
                wandb.termerror(f"{k} is not a regressor. Please try again.")
                test_passed = False
        elif k == "clusterer":
            if not (getattr(v, "_estimator_type", None) == "clusterer"):
                wandb.termerror(f"{k} is not a clusterer. Please try again.")
                test_passed = False
    return test_passed


def test_fitted(model):
    try:
        model.predict(np.zeros((7, 3)))
    except sklearn.exceptions.NotFittedError:
        wandb.termerror("Please fit the model before passing it in.")
        return False
    except AttributeError:
        # Some clustering models (LDA, PCA, Agglomerative) don't implement ``predict``
        try:
            sklearn.utils.validation.check_is_fitted(
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
        except sklearn.exceptions.NotFittedError:
            wandb.termerror("Please fit the model before passing it in.")
            return False
    except Exception:
        # Assume it's fitted, since ``NotFittedError`` wasn't raised
        return True


# Test Asummptions for plotting parameters and datasets
def test_missing(**kwargs):
    test_passed = True
    for k, v in kwargs.items():
        # Missing/empty params/datapoint arrays
        if v is None:
            wandb.termerror(f"{k} is None. Please try again.")
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
                wandb.termwarn(f"{k} contains {missing} missing values. ")
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
                    f"{k} contains values that are not numbers. Please vectorize, label encode or one hot encode {k} "
                    "and call the plotting function again."
                )
                test_passed = False
    return test_passed


def round_3(n):
    return round(n, 3)


def round_2(n):
    return round(n, 2)
