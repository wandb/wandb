import pathlib
import subprocess


def test_dspy_callback_end_to_end(wandb_backend_spy):
    script_path = pathlib.Path(__file__).parent / "dspy_callback.py"
    subprocess.check_call(["python", str(script_path)])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        # Telemetry: ensure dspy_callback feature flag was set
        telemetry = snapshot.telemetry(run_id=run_id)
        assert 73 in telemetry["3"]  # feature=dspy_callback

        # History: score should be logged at step 0
        history = snapshot.history(run_id=run_id)
        assert any(row.get("score") == 0.8 for row in history.values())

        # History: predictions and program signature tables should be present
        # predictions should be of type table-file,
        # program_signature should be of type incremental-table-file
        pred_table = history[0].get("predictions_0")
        assert isinstance(pred_table, dict) and pred_table.get("_type") == "table-file"
        prog_table = history[0].get("program_signature")
        assert (
            isinstance(prog_table, dict)
            and prog_table.get("_type") == "incremental-table-file"
        )

        # Config: fields from Evaluate instance should be present, but devset excluded
        config = snapshot.config(run_id=run_id)
        assert "num_threads" in config
        assert config["num_threads"] == {"value": 2}
        assert "auto" in config
        assert "devset" not in config

        # Summary: best_model_artifact key should be set by log_best_model
        summary = snapshot.summary(run_id=run_id)
        assert summary["score"] == 0.8
        assert summary["_step"] == 0
        assert "predictions_0" in summary
        assert "program_signature" in summary

        # Artifacts: dspy-program artifact should be present
        # artifacts = snapshot.artifacts(run_id=run_id)
        # print(artifacts)
        # assert "dspy-program" in artifacts
