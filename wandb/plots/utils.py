import wandb

# FIXME: do not import numpy/pandas/scipy, look at wandb.util.is_numpy_array() wandb.util.is_pandas* for examples
import numpy as np
import pandas as pd
import scipy

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
