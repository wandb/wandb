import sys

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 6), reason="xgboost 1.0.0 uses f strings")
if sys.version_info < (3, 6):
    pass
else:
    import xgboost as xgb

from sklearn.linear_model import ElasticNet
from sklearn.datasets import make_regression
from sklearn.model_selection import train_test_split

from wandb.xgboost import plot_feature_importances
import wandb
from wandb import wandb_run
from wandb.xgboost import wandb_callback

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History

History.keep_rows = True


@pytest.fixture
def dummy_data(request):
    data = np.array([[1, 2], [3, 4]])
    label = np.array([0, 1])
    dtrain = xgb.DMatrix(data, label=label)
    return dtrain


@pytest.mark.skipif(sys.version_info < (3, 6), reason="xgboost was segfaulting in CI")
def test_basic_xgboost(dummy_data, wandb_init_run):
    param = {'max_depth': 2, 'eta': 1, 'objective': 'binary:logistic'}
    num_round = 2
    xgb.train(param, dummy_data, num_round, callbacks=[wandb_callback()])


def test_feature_importance_attribute_does_not_exists(wandb_init_run):
    data = np.array([[1, 2], [3, 4]])
    label = np.array([0, 1])
    model = ElasticNet(random_state=42)
    model.fit(data, label)
    dummy_features = []

    result = plot_feature_importances(model, feature_names=dummy_features)

    assert result is None, \
        "Should have NOT returned any result, as feature_importances_ " \
        "attribute does NOT exist"


def test_feature_importance_attribute_exists_for_xgboost(wandb_init_run):
    X, y = make_regression(n_features=2, random_state=42)
    X_tr, X_val, y_tr, y_val = train_test_split(X, y, test_size=0.99, random_state=42)

    two_features = ['a', 'b']
    params_dict = {'colsample_bytree': 0.375, 'learning_rate': 0.08, 'max_depth': 10,
                   'subsample': 1, 'objective': 'reg:squarederror', 'eval_metric': 'rmse'}

    train = xgb.DMatrix(X_tr, y_tr)
    val = xgb.DMatrix(X_val, y_val)
    model = xgb.train(params_dict, train, evals=[(train, 'train'), (val, 'val')],
                      num_boost_round=2222, verbose_eval=0, early_stopping_rounds=100)


    result = plot_feature_importances(model, feature_names=two_features)

    assert isinstance(result, wandb.viz.Visualize), \
        "Should have returned a result, as feature_importances_ attribute does exist"
