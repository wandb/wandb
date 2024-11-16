import pathlib

import pytest


@pytest.mark.wandb_core_only
def test_classification(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "classification.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        config = snapshot.config(run_id=run_id)
        assert config["learner"]["value"]["gradient_booster"]["name"] == "gbtree"
        assert config["learner"]["value"]["objective"]["name"] == "multi:softprob"

        summary = snapshot.summary(run_id=run_id)
        assert summary["Feature Importance_table"]["_type"] == "table-file"
        assert summary["Feature Importance_table"]["ncols"] == 2
        assert summary["Feature Importance_table"]["nrows"] == 11
        assert summary["best_score"] == 1.0
        assert summary["epoch"] == 49
        assert summary["validation_0-auc"]["max"] == 1
        assert summary["validation_1-auc"]["max"] == 1
        assert summary["validation_0-mlogloss"]["min"] > 0.0
        assert summary["validation_1-mlogloss"]["min"] > 0.0

        telemetry = snapshot.telemetry(run_id=run_id)
        assert 31 in telemetry["3"]  # feature=xgboost_wandb_callback


@pytest.mark.wandb_core_only
def test_regression(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "regression.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        config = snapshot.config(run_id=run_id)
        assert config["learner"]["value"]["gradient_booster"]["name"] == "gbtree"
        assert config["learner"]["value"]["objective"]["name"] == "reg:squarederror"

        summary = snapshot.summary(run_id=run_id)
        assert summary["Feature Importance_table"]["_type"] == "table-file"
        assert summary["Feature Importance_table"]["ncols"] == 2
        assert summary["Feature Importance_table"]["nrows"] == 7
        assert summary["best_score"] > 0.5
        assert summary["best_iteration"] == 99
        assert summary["epoch"] == 99
        assert summary["validation_0-rmse"]["min"] > 0.0
        assert summary["validation_1-rmse"]["min"] > 0.0

        telemetry = snapshot.telemetry(run_id=run_id)
        assert 31 in telemetry["3"]  # feature=xgboost_wandb_callback
