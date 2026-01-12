from __future__ import annotations

import pathlib


def test_regression(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "regression.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        config = snapshot.config(run_id=run_id)
        assert config["classes_count"]["value"] == 0
        assert config["depth"]["value"] == 2
        assert config["eval_metric"]["value"] == "MultiClass"
        assert config["iterations"]["value"] == 10

        summary = snapshot.summary(run_id=run_id)
        assert summary["iteration@metric-period-1"] == 10
        assert summary["Feature Importance_table"]["_type"] == "table-file"
        assert summary["learn-MultiClass"] > 0.0
        assert summary["best_score"]["learn"]["MultiClass"] > 0.0

        telemetry = snapshot.telemetry(run_id=run_id)
        assert 27 in telemetry["3"]  # feature=catboost_wandb_callback
        assert 28 in telemetry["3"]  # feature=catboost_log_summary
