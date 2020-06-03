import wandb
from sklearn.datasets import make_regression
from catboost import CatBoostRegressor, CatBoostClassifier


def test_types(**kwargs):
    test_passed = True
    for k, v in kwargs.items():
        if k == 'model':
            if not (isinstance(v, CatBoostRegressor) or isinstance(v, CatBoostClassifier)):
                test_passed = False
                wandb.termerror("%s is not a regressor or classifier. Please try again." % (k))

    return test_passed


def test_fitted(model):
    try:
        X, y = make_regression(n_features=2, random_state=24)
        temp_model = model.copy()
        temp_model.fit(X, y, verbose=False)
    except Exception:
        wandb.termerror("Please fit the model before passing it in.")
        return False

    return True
