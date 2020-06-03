import pytest
import numpy as np
import lightgbm as lgb
import wandb
import sys
from wandb import wandb_run
from wandb.lightgbm import plot_feature_importances, wandb_callback

from sklearn.linear_model import ElasticNet
from sklearn.datasets import make_classification

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History

History.keep_rows = True


@pytest.fixture
def dummy_data(request):
    data = np.array([[1, 2], [3, 4]])
    label = np.array([0, 1])
    dtrain = lgb.Dataset(data, label=label)
    return dtrain


@pytest.mark.skipif(sys.version_info < (3, 6), reason="lightgbm was segfaulting in CI")
def test_basic_lightgbm(dummy_data, wandb_init_run):
    param = {'max_depth': 2, 'eta': 1}
    num_round = 2
    lgb.train(param, dummy_data, num_round, callbacks=[wandb_callback()])


def test_feature_importance_attribute_does_not_exists(wandb_init_run):
    data = np.array([[1, 2], [3, 4]])
    label = np.array([0, 1])
    model = ElasticNet(random_state=42)
    model.fit(data, label)
    dummy_features = []

    result = plot_feature_importances(model, feature_names=dummy_features)

    assert result is None, "Should have NOT returned any result, as feature_importances() attribute does NOT exist"


def test_feature_importance_attribute_exists_for_lightgbm(wandb_init_run):
    X, y = make_classification(n_samples=100, n_features=10, n_informative=2, n_redundant=5, random_state=42)
    ten_features = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j']
    params = {'learning_rate': 0.01, 'max_depth': -1, 'num_leaves': 4, 'objective': 'fair', 'boosting': 'gbdt',
              'boost_from_average': True, 'feature_fraction': 0.9, 'bagging_freq': 1, 'bagging_fraction': 0.5,
              'early_stopping_rounds': 200, 'metric': 'rmse', 'max_bin': 255, 'n_jobs': -1, 'verbosity': -1,
              'bagging_seed': 1234}
    dataset = lgb.Dataset(X, y)
    model = lgb.train(params, dataset, valid_sets=[dataset], valid_names=['train'], callbacks=[wandb_callback()])

    result = plot_feature_importances(model, feature_names=ten_features)

    assert isinstance(result,
                      wandb.viz.Visualize), "Should have returned a result, as feature_importances() attribute does exist"
