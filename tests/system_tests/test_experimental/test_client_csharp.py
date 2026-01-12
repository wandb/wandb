from __future__ import annotations

import os
import pathlib
import subprocess


def test_client_sharp(wandb_backend_spy):
    script_path = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "experimental"
        / "client-csharp"
        / "examples"
        / "Basic"
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

        tags = snapshot.tags(run_id=run_id)
        assert "c" in tags
        assert "sharp" in tags
