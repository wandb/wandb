import os
import pathlib
import subprocess

import pytest


@pytest.mark.timeout(300)
def test_client_rust(wandb_backend_spy):
    script_path = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "experimental"
        / "rust-sdk"
        / "examples"
        / "basic"
        / "build_and_run.sh"
    )

    subprocess.run([str(script_path)], check=True, env=os.environ)

    with wandb_backend_spy.freeze() as snapshot:
        runs = snapshot.run_ids()
        assert len(runs) == 1
        run_id = runs.pop()

        config = snapshot.config(run_id=run_id)
        assert config["batch_size"]["value"] == 64
        assert config["learning_rate"]["value"] == 3e-4

        history = snapshot.history(run_id=run_id)
        assert len(history) == 4

        summary = snapshot.summary(run_id=run_id)
        assert summary["best_recall"] == 0.875

        tags = snapshot.tags(run_id=run_id)
        assert "r" in tags
        assert "ust" in tags

        assert snapshot.exit_code(run_id=run_id) == 0
