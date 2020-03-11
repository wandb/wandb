import wandb

# FIXME: look at wandb.util.is_numpy_array() wandb.util.is_pandas* for examples
np = util.get_module("numpy", required="Logging plots requires numpy")
pd = util.get_module("pandas", required="Logging dataframes requires pandas")
scipy = util.get_module("scipy", required="Logging scipy matrices requires scipy")
spacy = util.get_module("spacy", required="Logging NER and POD requires spacy")
sklearn = util.get_module("sklearn", required="Logging scikit plots requires sklearn")
# eli5

# FIXME: add types test
# FIXME: add fitted test

# Test Asummptions for plotting parameters and datasets
def test_missing(**kwargs):
    test_passed = True
    for k,v in kwargs.items():
        # Missing/empty params/datapoint arrays
        if v is None:
            wandb.termerror("%s is None. Please try again." % (k))
            test_passed = False
        if ((k == 'X') or (k == 'X_test')):
            if isinstance(v, scipy.sparse.csr.csr_matrix):
                v = v.toarray()
            elif isinstance(v, (pd.DataFrame, pd.Series)):
                v = v.to_numpy()
            elif isinstance(v, list):
                v = np.asarray(v)

            # Warn the user about missing values
            missing = 0
            missing = np.count_nonzero(pd.isnull(v))
            if missing>0:
                wandb.termwarn("%s contains %d missing values. " % (k,missing))
                test_passed = False
            # Ensure the dataset contains only integers
            non_nums = 0
            if v.ndim == 1:
                non_nums = sum(1 for val in v if (not isinstance(val, (int, float, complex)) and not isinstance(val,np.number)))
            else:
                non_nums = sum(1 for sl in v for val in sl if (not isinstance(val, (int, float, complex)) and not isinstance(val,np.number)))
            if non_nums>0:
                wandb.termerror("%s contains values that are not numbers. Please vectorize, label encode or one hot encode %s and call the plotting function again." % (k,k))
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

def encode_labels(df):
    le = sklearn.preprocessing.LabelEncoder()
    # apply le on categorical feature columns
    categorical_cols = df.select_dtypes(exclude=['int','float','float64','float32','int32','int64']).columns
    df[categorical_cols] = df[categorical_cols].apply(lambda col: le.fit_transform(col))
