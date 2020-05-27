import wandb
from sklearn.datasets import make_regression
import xgboost as xgb


def test_types(**kwargs):
    test_passed = True
    for k, v in kwargs.items():
        if k == 'model':
            print("type of v", type(v))
            if not (isinstance(v, xgb.core.Booster)):
                test_passed = False
                wandb.termerror("%s is not a regressor or classifier. Please try again." % (k))

    return test_passed
