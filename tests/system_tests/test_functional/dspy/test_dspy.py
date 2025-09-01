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
