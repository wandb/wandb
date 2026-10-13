import numpy as np
import pytest

catboost = pytest.importorskip("catboost")

from wandb.integration.catboost import WandbCallback  # noqa: E402


def test_logs_each_evaluation(mocker):
    mocker.patch("wandb.run")
    log = mocker.patch("wandb.log")
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 4))
    y = x[:, 0] + rng.normal(size=200)
    model = catboost.CatBoostRegressor(iterations=12, metric_period=5, verbose=False)

    model.fit(
        x[:150],
        y[:150],
        eval_set=(x[150:], y[150:]),
        callbacks=[WandbCallback(metric_period=5)],
    )

    logged = [call.args[0] for call in log.call_args_list]
    rmse = [d["validation-RMSE"] for d in logged if "validation-RMSE" in d]
    iterations = [
        d["iteration@metric-period-5"]
        for d in logged
        if "iteration@metric-period-5" in d
    ]
    assert rmse == model.get_evals_result()["validation"]["RMSE"]
    assert iterations == [1, 6, 11, 12]
