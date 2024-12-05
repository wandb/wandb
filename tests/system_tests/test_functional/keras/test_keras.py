import pathlib

import pytest


@pytest.mark.wandb_core_only
def test_eval_tables_builder(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "keras_eval_tables_builder.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        telemetry = snapshot.telemetry(run_id=run_id)
        assert 40 in telemetry["3"]  # feature=keras_wandb_eval_callback


@pytest.mark.wandb_core_only
def test_metrics_logger_epochwise(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "keras_metrics_logger_epochwise.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        telemetry = snapshot.telemetry(run_id=run_id)
        assert 38 in telemetry["3"]  # feature=keras

        summary = snapshot.summary(run_id=run_id)
        assert summary["epoch/epoch"] == 1
        assert "epoch/accuracy" in summary
        assert "epoch/val_accuracy" in summary
        assert "epoch/learning_rate" in summary


@pytest.mark.wandb_core_only
def test_metrics_logger(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "keras_metrics_logger.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        telemetry = snapshot.telemetry(run_id=run_id)
        assert 38 in telemetry["3"]

        summary = snapshot.summary(run_id=run_id)
        assert summary["epoch/epoch"] == 1
        assert "epoch/accuracy" in summary
        assert "epoch/val_accuracy" in summary
        assert "batch/accuracy" in summary
        assert summary["batch/batch_step"] == 7
        assert "batch/learning_rate" in summary


@pytest.mark.wandb_core_only
def test_model_checkpoint(wandb_backend_spy, execute_script):
    script_path = pathlib.Path(__file__).parent / "keras_model_checkpoint.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        telemetry = snapshot.telemetry(run_id=run_id)
        assert 39 in telemetry["3"]  # feature=keras_wandb_model_checkpoint


@pytest.mark.wandb_core_only
def test_deprecated_keras_callback(
    wandb_backend_spy,
    execute_script,
    mock_wandb_log,
):
    script_path = pathlib.Path(__file__).parent / "keras_deprecated.py"
    execute_script(script_path)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        summary = snapshot.summary(run_id=run_id)
        assert "accuracy" in summary
        assert "val_loss" in summary
        assert "best_val_loss" in summary
        assert summary["epoch"] == 6
        assert "best_epoch" in summary

        telemetry = snapshot.telemetry(run_id=run_id)
        assert 8 in telemetry["3"]  # feature=keras

        assert mock_wandb_log.warned(
            "WandbCallback is deprecated and will be removed in a future release."
        )
