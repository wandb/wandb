from typing import Iterable, Sequence

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
            wandb.termerror("{} is None. Please try again.".format(k))
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
                    f"{k} contains values that are not numbers. Please vectorize, "
                    f"label encode or one hot encode {k} and call the plotting function again."
                )
                test_passed = False
    return test_passed


def test_fitted(model):
    np = util.get_module("numpy", required="Logging plots requires numpy")
    _ = util.get_module("pandas", required="Logging dataframes requires pandas")
    _ = util.get_module("scipy", required="Logging scipy matrices requires scipy")
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
    _ = util.get_module("pandas", required="Logging dataframes requires pandas")
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
    _ = util.get_module("scipy", required="Logging scipy matrices requires scipy")

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
                wandb.termerror("{} is not an array. Please try again.".format(k))
                test_passed = False
        # check for classifier types
        if k == "model":
            if (not base.is_classifier(v)) and (not base.is_regressor(v)):
                wandb.termerror(
                    "{} is not a classifier or regressor. Please try again.".format(k)
                )
                test_passed = False
        elif k == "clf" or k == "binary_clf":
            if not (base.is_classifier(v)):
                wandb.termerror("{} is not a classifier. Please try again.".format(k))
                test_passed = False
        elif k == "regressor":
            if not base.is_regressor(v):
                wandb.termerror("{} is not a regressor. Please try again.".format(k))
                test_passed = False
        elif k == "clusterer":
            if not (getattr(v, "_estimator_type", None) == "clusterer"):
                wandb.termerror("{} is not a clusterer. Please try again.".format(k))
                test_passed = False
    return test_passed
