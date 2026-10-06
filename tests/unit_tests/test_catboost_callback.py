"""The CatBoost callback logs every evaluation CatBoost makes, when it makes it."""

import importlib
from unittest import mock

import numpy as np
import pytest


def _import_or_skip(module: str):
    # An installed but unloadable library can raise more than ImportError.
    try:
        return importlib.import_module(module)
    except Exception as e:
        pytest.skip(f"{module} is not usable here: {e}")


def test_logs_each_evaluation_including_the_last():
    catboost = _import_or_skip("catboost")
    from wandb.integration.catboost import WandbCallback

    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 4))
    y = x[:, 0] + rng.normal(size=200)
    model = catboost.CatBoostRegressor(
        iterations=12, metric_period=5, verbose=False, random_seed=0
    )

    with mock.patch("wandb.run", mock.Mock()), mock.patch("wandb.log") as log:
        model.fit(
            x[:150],
            y[:150],
            eval_set=(x[150:], y[150:]),
            callbacks=[WandbCallback(metric_period=5)],
        )

    logged = [c.args[0] for c in log.call_args_list]
    values = [d["validation-RMSE"] for d in logged if "validation-RMSE" in d]
    iterations = [
        d["iteration@metric-period-5"]
        for d in logged
        if "iteration@metric-period-5" in d
    ]
    # CatBoost evaluates on iterations 1, 6 and 11 and on the last one.
    assert values == model.get_evals_result()["validation"]["RMSE"]
    assert iterations == [1, 6, 11, 12]
