import pathlib

import pytest


@pytest.mark.wandb_core_only
def test_classification(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "classification.py"
        execute_script(script_path)

    context = relay.context
    run_ids = context.get_run_ids()
    assert len(run_ids) == 1
    run_id = run_ids[0]

    config = context.get_run_config(run_id)
    config["learner"]["value"]["gradient_booster"]["name"] = "gbtree"
    config["learner"]["value"]["objective"]["name"] = "multi:softprob"

    summary = context.get_run_summary(run_id)
    assert summary["Feature Importance_table"]["_type"] == "table-file"
    assert summary["Feature Importance_table"]["ncols"] == 2
    assert summary["Feature Importance_table"]["nrows"] == 11
    assert summary["best_score"] == 1.0
    assert summary["epoch"] == 49
    assert summary["validation_0-auc"]["max"] == 1
    assert summary["validation_1-auc"]["max"] == 1
    assert summary["validation_0-mlogloss"]["min"] > 0.0
    assert summary["validation_1-mlogloss"]["min"] > 0.0

    telemetry = context.get_run_telemetry(run_id)
    assert 31 in telemetry["3"]  # feature=xgboost_wandb_callback


@pytest.mark.wandb_core_only
def test_regression(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "regression.py"
        execute_script(script_path)

    context = relay.context
    run_ids = context.get_run_ids()
    assert len(run_ids) == 1
    run_id = run_ids[0]

    config = context.get_run_config(run_id)
    config["learner"]["value"]["gradient_booster"]["name"] = "gbtree"
    config["learner"]["value"]["objective"]["name"] = "reg:squarederror"

    summary = context.get_run_summary(run_id)
    assert summary["Feature Importance_table"]["_type"] == "table-file"
    assert summary["Feature Importance_table"]["ncols"] == 2
    assert summary["Feature Importance_table"]["nrows"] == 7
    assert summary["best_score"] > 0.5
    assert summary["best_iteration"] == 99
    assert summary["epoch"] == 99
    assert summary["validation_0-rmse"]["min"] > 0.0
    assert summary["validation_1-rmse"]["min"] > 0.0

    telemetry = context.get_run_telemetry(run_id)
    assert 31 in telemetry["3"]  # feature=xgboost_wandb_callback
