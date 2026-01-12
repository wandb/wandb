from __future__ import annotations

import pathlib

import pytest


@pytest.mark.parametrize(
    "start_method",
    ["spawn", "forkserver"],
)
def test_share_child_base(
    wandb_backend_spy,
    start_method,
    execute_script,
):
    script_path = pathlib.Path(__file__).parent / "share_child_base.py"
    execute_script(script_path, "--start-method", start_method)

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1

        run_id = run_ids.pop()
        history = snapshot.history(run_id=run_id)
        assert history[0]["s1"] == 11
        assert history[1]["s1"] == 21

        config = snapshot.config(run_id=run_id)
        assert config["c1"]["value"] == 11
        assert config["c2"]["value"] == 22
