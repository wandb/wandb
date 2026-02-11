from __future__ import annotations

import importlib
from typing import Any, Callable

import pytest


@pytest.fixture
def run_and_snapshot(wandb_backend_spy):
    """Factory fixture to run a dspy example module and collect W&B snapshot.

    Args:
        wandb_backend_spy: Spy fixture for W&B backend.

    Returns:
        Callable: A function that accepts a module and optional setup/cleanup callbacks,
        runs the module's `main()`, and returns a dict with `snapshot`, `run_id`,
        `history`, `summary`, `config`, and any `extras` from setup.

    Examples:
        >>> def setup(spy):
        ...     return {"x": 1}
        >>> # mod = importlib.import_module("...dspy_callback")  # doctest: +SKIP
        >>> # result = run_and_snapshot(mod, setup=setup)  # doctest: +SKIP
    """

    def _runner(
        module: Any,
        *,
        setup: Callable[[Any], dict[str, Any]] | None = None,
        cleanup: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        if setup is not None:
            extras = setup(wandb_backend_spy) or {}

        module.main()

        if cleanup is not None:
            try:
                cleanup()
            except Exception:
                pass

        with wandb_backend_spy.freeze() as snapshot:
            run_ids = snapshot.run_ids()
            assert len(run_ids) == 1
            run_id = run_ids.pop()
            telemetry = snapshot.telemetry(run_id=run_id)
            history = snapshot.history(run_id=run_id)
            summary = snapshot.summary(run_id=run_id)
            config = snapshot.config(run_id=run_id)
            return {
                "run_id": run_id,
                "telemetry": telemetry,
                "history": history,
                "summary": summary,
                "config": config,
                "extras": extras,
            }

    return _runner


@pytest.mark.skip(reason="flaky")
def test_dspy_callback_end_to_end(run_and_snapshot):
    # Capture artifact-related GraphQL operations before running the script
    def _setup(spy):
        gql = spy.gql
        create_artifact_spy = gql.Capture()
        use_artifact_spy = gql.Capture()
        create_artifact_files_spy = gql.Capture()
        spy.stub_gql(
            gql.Matcher(operation="CreateArtifact"),
            create_artifact_spy,
        )
        spy.stub_gql(
            gql.Matcher(operation="UseArtifact"),
            use_artifact_spy,
        )
        spy.stub_gql(
            gql.Matcher(operation="CreateArtifactFiles"),
            create_artifact_files_spy,
        )
        return {
            "create_artifact_spy": create_artifact_spy,
            "use_artifact_spy": use_artifact_spy,
            "create_artifact_files_spy": create_artifact_files_spy,
        }

    from . import dspy_callback as _dspy_callback

    result = run_and_snapshot(_dspy_callback, setup=_setup)

    _ = result["run_id"]
    telemetry = result["telemetry"]
    history = result["history"]
    summary = result["summary"]
    config = result["config"]
    create_artifact_files_spy = result["extras"]["create_artifact_files_spy"]
    create_artifact_spy = result["extras"]["create_artifact_spy"]

    # Telemetry: ensure `dspy_callback` feature flag was set
    assert 73 in telemetry["3"]  # feature=dspy_callback

    # History: score should be logged at step 0
    assert any(row.get("score") == 0.8 for row in history.values())

    # History: predictions and program signature tables should be present
    pred_table = history[0].get("predictions_0")
    assert isinstance(pred_table, dict) and pred_table.get("_type") == "table-file"
    prog_table = history[0].get("program_signature")
    assert (
        isinstance(prog_table, dict)
        and prog_table.get("_type") == "incremental-table-file"
    )

    # Config: fields from Evaluate instance should be present, but devset excluded
    assert "num_threads" in config
    assert config["num_threads"] == {"value": 2}
    assert "auto" in config
    assert "devset" not in config

    # Summary
    assert summary["score"] == 0.8
    assert summary["_step"] == 0
    assert "predictions_0" in summary
    assert "program_signature" in summary

    # Artifacts
    assert create_artifact_spy.total_calls >= 5

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


def test_dspy_callback_log_results_false(run_and_snapshot):
    """Do not log predictions table when log_results=False; still log score and program."""
    from . import dspy_callback_log_results_false as _nolog

    result = run_and_snapshot(_nolog)
    history = result["history"]
    summary = result["summary"]

    # Ensure there is no predictions table logged
    assert "predictions_0" not in history[0]

    # Program signature should still be present
    prog_table = history[0].get("program_signature")
    assert (
        isinstance(prog_table, dict)
        and prog_table.get("_type") == "incremental-table-file"
    )

    assert summary["score"] == 0.8
    assert "program_signature" in summary
    assert "predictions_0" not in summary


def test_dspy_callback_unexpected_outputs(run_and_snapshot):
    """Unexpected outputs type: skip score and predictions; still log program signature."""
    from . import dspy_callback_unexpected as _unexpected

    result = run_and_snapshot(_unexpected)
    history = result["history"]
    summary = result["summary"]

    assert all("score" not in row for row in history.values())
    assert "predictions_0" not in history[0]
    prog_table = history[0].get("program_signature")
    assert (
        isinstance(prog_table, dict)
        and prog_table.get("_type") == "incremental-table-file"
    )

    assert "score" not in summary
    assert "predictions_0" not in summary
    assert "program_signature" in summary


def test_dspy_callback_exception_path(run_and_snapshot):
    """Exception passed: skip score and predictions; still log program signature."""
    from . import dspy_callback_exception as _exception

    result = run_and_snapshot(_exception)
    history = result["history"]
    summary = result["summary"]

    assert all("score" not in row for row in history.values())
    assert "predictions_0" not in history[0]
    prog_table = history[0].get("program_signature")
    assert (
        isinstance(prog_table, dict)
        and prog_table.get("_type") == "incremental-table-file"
    )

    assert "score" not in summary
    assert "predictions_0" not in summary
    assert "program_signature" in summary


def test_dspy_callback_multiple_steps(run_and_snapshot):
    """Two evaluate steps: predictions_0 and predictions_1, and program signature across steps."""
    from . import dspy_callback_multiple_steps as _multi

    result = run_and_snapshot(_multi)
    history = result["history"]
    summary = result["summary"]

    # Both steps should have been logged
    assert "predictions_0" in history[0]
    assert "predictions_1" in history[1]
    # Program signature should be logged both times as incremental table
    prog0 = history[0].get("program_signature")
    prog1 = history[1].get("program_signature")
    assert isinstance(prog0, dict) and prog0.get("_type") == "incremental-table-file"
    assert isinstance(prog1, dict) and prog1.get("_type") == "incremental-table-file"

    assert "predictions_0" in summary
    assert "predictions_1" in summary
    # Latest score should be from the last step
    assert summary["score"] == 0.9


def test_dspy_callback_no_program(run_and_snapshot):
    """No program in inputs of on_evaluate_start: still logs program_signature with minimal columns."""
    from . import dspy_callback_no_program as _no_program

    result = run_and_snapshot(_no_program)
    history = result["history"]
    summary = result["summary"]

    assert "predictions_0" in history[0]
    prog_table = history[0].get("program_signature")
    assert (
        isinstance(prog_table, dict)
        and prog_table.get("_type") == "incremental-table-file"
    )

    assert "program_signature" in summary


def test_dspy_callback_completions(run_and_snapshot):
    """Use a dummy dspy.Completions with items() to exercise the completions branch."""
    from . import dspy_callback_completions as _completions

    def _cleanup():
        import dspy as _dspy  # type: ignore

        importlib.reload(_dspy)

    result = run_and_snapshot(_completions, cleanup=_cleanup)
    history = result["history"]
    summary = result["summary"]

    # Predictions table should be present; content correctness is validated upstream
    assert "predictions_0" in history[0]
    assert "predictions_0" in summary
