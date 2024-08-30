import pathlib

import pytest

# TODO: these tests do not test much beyond the callback initialization.
# We should add tests that check that the callbacks actually log the expected data.


@pytest.mark.wandb_core_only
def test_eval_tables_builder(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "keras_eval_tables_builder.py"
        execute_script(script_path)
    print(relay.context._entries)
    runs = run_id = relay.context.get_run_ids()
    assert len(runs) == 1
    run_id = runs[0]

    telemetry = relay.context.get_run_telemetry(run_id)
    assert 40 in telemetry["3"]  # feature=keras_wandb_eval_callback


@pytest.mark.wandb_core_only
def test_metrics_logger_epochwise(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = (
            pathlib.Path(__file__).parent / "keras_metrics_logger_epochwise.py"
        )
        execute_script(script_path)

    runs = run_id = relay.context.get_run_ids()
    assert len(runs) == 1
    run_id = runs[0]

    telemetry = relay.context.get_run_telemetry(run_id)
    assert 38 in telemetry["3"]  # feature=keras

    summary = relay.context.get_run_summary(run_id)
    assert summary["epoch/epoch"] == 1
    assert summary["epoch/accuracy"] == pytest.approx(0.11999999)
    assert summary["epoch/loss"] == pytest.approx(2.3033, rel=1e-4)
    assert summary["epoch/val_accuracy"] == pytest.approx(0.11999999)
    assert summary["epoch/val_loss"] == pytest.approx(2.3033, rel=1e-4)
    assert summary["epoch/learning_rate"] == pytest.approx(1e-5)


@pytest.mark.wandb_core_only
def test_metrics_logger(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "keras_metrics_logger.py"
        execute_script(script_path)

    runs = run_id = relay.context.get_run_ids()
    assert len(runs) == 1
    run_id = runs[0]

    telemetry = relay.context.get_run_telemetry(run_id)
    assert 38 in telemetry["3"]

    summary = relay.context.get_run_summary(run_id)
    assert summary["epoch/epoch"] == 1
    assert summary["epoch/accuracy"] == pytest.approx(0.14, rel=1e-2)
    assert summary["epoch/loss"] == pytest.approx(2.302, rel=1e-3)
    assert summary["epoch/val_accuracy"] == pytest.approx(0.140, rel=1e-3)
    assert summary["epoch/val_loss"] == pytest.approx(2.302, rel=1e-3)
    assert summary["batch/accuracy"] == pytest.approx(0.14, rel=1e-3)
    assert summary["batch/loss"] == pytest.approx(2.302, rel=1e-3)
    assert summary["batch/batch_step"] == 7
    assert summary["batch/learning_rate"] == pytest.approx(0.00999999, rel=1e-5)


@pytest.mark.wandb_core_only
def test_model_checkpoint(user, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "keras_model_checkpoint.py"
        execute_script(script_path)
    print(relay.context._entries)
    runs = run_id = relay.context.get_run_ids()
    assert len(runs) == 1
    run_id = runs[0]

    telemetry = relay.context.get_run_telemetry(run_id)
    assert 39 in telemetry["3"]  # feature=keras_wandb_model_checkpoint
