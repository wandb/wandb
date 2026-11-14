"""The XGBoost and LightGBM callbacks summarize each metric at its best step."""

import importlib
from types import SimpleNamespace
from unittest import mock

import pytest


def _import_or_skip(module: str):
    # Installed but unloadable (e.g. no libomp on macOS runners) raises
    # XGBoostError or OSError rather than ImportError, so skip on any error.
    try:
        return importlib.import_module(module)
    except Exception as e:
        pytest.skip(f"{module} is not usable here: {e}")


@pytest.mark.parametrize(
    "metric_name, summary",
    [
        ("auc", "max"),
        ("ndcg@5", "max"),
        ("map@3", "max"),
        ("error@0.6", "min"),
        ("logloss", "min"),
    ],
)
def test_xgboost_parameterized_metrics_get_a_best_summary(metric_name, summary):
    _import_or_skip("xgboost")
    from wandb.integration.xgboost import WandbCallback

    with mock.patch("wandb.define_metric") as define_metric:
        WandbCallback._define_metric(None, "validation_0", metric_name)

    define_metric.assert_called_once_with(
        f"validation_0-{metric_name}".replace(".", "\\."), summary=summary
    )


def test_lightgbm_uses_the_metric_direction_lightgbm_reports():
    _import_or_skip("lightgbm")
    from wandb.integration.lightgbm import wandb_callback

    callback = wandb_callback(log_params=False)
    env = SimpleNamespace(
        evaluation_result_list=[
            ("valid", "binary_error", 0.2, False),
            ("valid", "ndcg@3", 0.6, True),
            ("cv_agg", "valid map@3", 0.7, True, 0.01),
        ]
    )
    with mock.patch("wandb.define_metric") as define_metric:
        callback._init(env)

    assert define_metric.call_args_list == [
        mock.call("valid_binary_error", summary="min"),
        mock.call("valid_ndcg@3", summary="max"),
        mock.call("valid_map@3-mean", summary="max"),
    ]
