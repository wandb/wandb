import pathlib
import subprocess


def test_dspy_callback_end_to_end(wandb_backend_spy):
    # Capture artifact-related GraphQL operations before running the script
    gql = wandb_backend_spy.gql
    create_artifact_spy = gql.Capture()
    use_artifact_spy = gql.Capture()
    create_artifact_files_spy = gql.Capture()
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="CreateArtifact"),
        create_artifact_spy,
    )
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="UseArtifact"),
        use_artifact_spy,
    )
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="CreateArtifactFiles"),
        create_artifact_files_spy,
    )

    script_path = pathlib.Path(__file__).parent / "dspy_callback.py"
    subprocess.check_call(["python", str(script_path)])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        # Telemetry: ensure `dspy_callback` feature flag was set
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

        # Summary
        summary = snapshot.summary(run_id=run_id)
        assert summary["score"] == 0.8
        assert summary["_step"] == 0
        assert "predictions_0" in summary
        assert "program_signature" in summary

        # Artifacts
        assert create_artifact_spy.total_calls == 5

        check_uploaded_files = ["program.json", "program.pkl"]
        for req in create_artifact_files_spy.requests:
            artifact_files = req.variables.get("artifactFiles", [])
            # artifact produced when `save_program=True`
            if len(artifact_files) == 2:
                spec_0 = artifact_files[0]
                spec_1 = artifact_files[1]
                assert spec_0.get("name") == "metadata.json"
                assert spec_1.get("name") == "program.pkl"

            # Check for two artifacts files when `save_program=False`
            # and filetype is `json` or `pkl`
            for spec in artifact_files:
                name = spec.get("name")
                if name in check_uploaded_files:
                    check_uploaded_files.remove(name)
        assert len(check_uploaded_files) == 0


def test_dspy_callback_log_results_false(wandb_backend_spy):
    """Do not log predictions table when log_results=False; still log score and program."""
    script_path = pathlib.Path(__file__).parent / "dspy_callback_log_results_false.py"
    subprocess.check_call(["python", str(script_path)])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        history = snapshot.history(run_id=run_id)
        # Ensure there is no predictions table logged
        assert "predictions_0" not in history[0]

        # Program signature should still be present
        prog_table = history[0].get("program_signature")
        assert (
            isinstance(prog_table, dict)
            and prog_table.get("_type") == "incremental-table-file"
        )

        summary = snapshot.summary(run_id=run_id)
        assert summary["score"] == 0.8
        assert "program_signature" in summary
        assert "predictions_0" not in summary


def test_dspy_callback_unexpected_outputs(wandb_backend_spy):
    """Unexpected outputs type: skip score and predictions; still log program signature."""
    script_path = pathlib.Path(__file__).parent / "dspy_callback_unexpected.py"
    subprocess.check_call(["python", str(script_path)])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        history = snapshot.history(run_id=run_id)
        assert all("score" not in row for row in history.values())
        assert "predictions_0" not in history[0]
        prog_table = history[0].get("program_signature")
        assert (
            isinstance(prog_table, dict)
            and prog_table.get("_type") == "incremental-table-file"
        )

        summary = snapshot.summary(run_id=run_id)
        assert "score" not in summary
        assert "predictions_0" not in summary
        assert "program_signature" in summary


def test_dspy_callback_exception_path(wandb_backend_spy):
    """Exception passed: skip score and predictions; still log program signature."""
    script_path = pathlib.Path(__file__).parent / "dspy_callback_exception.py"
    subprocess.check_call(["python", str(script_path)])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        history = snapshot.history(run_id=run_id)
        assert all("score" not in row for row in history.values())
        assert "predictions_0" not in history[0]
        prog_table = history[0].get("program_signature")
        assert (
            isinstance(prog_table, dict)
            and prog_table.get("_type") == "incremental-table-file"
        )

        summary = snapshot.summary(run_id=run_id)
        assert "score" not in summary
        assert "predictions_0" not in summary
        assert "program_signature" in summary


def test_dspy_callback_multiple_steps(wandb_backend_spy):
    """Two evaluate steps: predictions_0 and predictions_1, and program signature across steps."""
    script_path = pathlib.Path(__file__).parent / "dspy_callback_multiple_steps.py"
    subprocess.check_call(["python", str(script_path)])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        history = snapshot.history(run_id=run_id)
        # Both steps should have been logged
        assert "predictions_0" in history[0]
        assert "predictions_1" in history[1]
        # Program signature should be logged both times as incremental table
        prog0 = history[0].get("program_signature")
        prog1 = history[1].get("program_signature")
        assert isinstance(prog0, dict) and prog0.get("_type") == "incremental-table-file"
        assert isinstance(prog1, dict) and prog1.get("_type") == "incremental-table-file"

        summary = snapshot.summary(run_id=run_id)
        assert "predictions_0" in summary
        assert "predictions_1" in summary
        # Latest score should be from the last step
        assert summary["score"] == 0.9


def test_dspy_callback_no_program(wandb_backend_spy):
    """No program in inputs of on_evaluate_start: still logs program_signature with minimal columns."""
    script_path = pathlib.Path(__file__).parent / "dspy_callback_no_program.py"
    subprocess.check_call(["python", str(script_path)])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        history = snapshot.history(run_id=run_id)
        assert "predictions_0" in history[0]
        prog_table = history[0].get("program_signature")
        assert (
            isinstance(prog_table, dict)
            and prog_table.get("_type") == "incremental-table-file"
        )

        summary = snapshot.summary(run_id=run_id)
        assert "program_signature" in summary


def test_dspy_callback_completions(wandb_backend_spy):
    """Use a dummy dspy.Completions with items() to exercise the completions branch."""
    script_path = pathlib.Path(__file__).parent / "dspy_callback_completions.py"
    subprocess.check_call(["python", str(script_path)])

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = run_ids.pop()

        history = snapshot.history(run_id=run_id)
        # Predictions table should be present; content correctness is validated upstream
        assert "predictions_0" in history[0]

        summary = snapshot.summary(run_id=run_id)
        assert "predictions_0" in summary
