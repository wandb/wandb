import numpy as np
from sklearn.linear_model import ElasticNet
from sklearn.datasets import make_regression, make_classification
from catboost import CatBoostRegressor, CatBoostClassifier

import wandb

from wandb.catboost import plot_feature_importances

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History

History.keep_rows = True


def test_feature_importance_attribute_does_not_exists(wandb_init_run):
    data = np.array([[1, 2], [3, 4]])
    label = np.array([0, 1])
    model = ElasticNet(random_state=42)
    model.fit(data, label)
    dummy_features = []

    result = plot_feature_importances(model, feature_names=dummy_features)

    assert result is None, "Should have NOT returned any result, as feature_importances_ attribute does NOT exist"


def test_feature_importance_attribute_exists_for_catboostregressor(wandb_init_run):
    X, y = make_regression(n_features=2, random_state=42)
    two_features = ['a', 'b']
    model = CatBoostRegressor(random_state=42, early_stopping_rounds=10)
    model = model.fit(X, y)

    result = plot_feature_importances(model, feature_names=two_features)

    assert isinstance(result,
                      wandb.viz.Visualize), "Should have returned a result, as feature_importances_ attribute does exist"


def test_feature_importance_attribute_exists_for_catboostclassifier(wandb_init_run):
    X, y = make_classification(n_samples=100, n_features=10, n_informative=2, n_redundant=5, random_state=42)
    ten_features = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j']
    model = CatBoostClassifier(random_state=42, early_stopping_rounds=10)
    model = model.fit(X, y)

    result = plot_feature_importances(model, feature_names=ten_features)

    assert isinstance(result,
                      wandb.viz.Visualize), "Should have returned a result, as feature_importances_ attribute does exist"
