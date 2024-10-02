import pathlib

import pytest


@pytest.mark.wandb_core_only
def test_regression(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "regression.py"
        execute_script(script_path)

    run_ids = relay.context.get_run_ids()
    assert len(run_ids) == 1
    run_id = run_ids[0]

    config = relay.context.get_run_config(run_id)
    assert config["classes_count"]["value"] == 0
    assert config["depth"]["value"] == 2
    assert config["eval_metric"]["value"] == "MultiClass"
    assert config["iterations"]["value"] == 10

    summary = relay.context.get_run_summary(run_id)
    assert summary["iteration@metric-period-1"] == 10
    assert summary["Feature Importance_table"]["_type"] == "table-file"
    assert summary["learn-MultiClass"] > 0.0
    assert summary["best_score"]["learn"]["MultiClass"] > 0.0

    telemetry = relay.context.get_run_telemetry(run_id)
    assert 27 in telemetry["3"]  # feature=catboost_wandb_callback
    assert 28 in telemetry["3"]  # feature=catboost_log_summary
