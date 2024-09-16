import os
import pathlib
import subprocess

import pytest


@pytest.mark.wandb_core_only
def test_client_sharp(user, relay_server):
    script_path = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "experimental"
        / "client-csharp"
        / "examples"
        / "Basic"
        / "build_and_run.sh"
    )

    with relay_server() as relay:
        subprocess.run([str(script_path)], check=True, env=os.environ)

    runs = relay.context.get_run_ids()
    assert len(runs) == 1
    run_id = runs[0]

    config = relay.context.get_run_config(run_id)
    assert config["batch_size"]["value"] == 64

    history = relay.context.get_run_history(run_id)
    assert len(history) == 3
