import pathlib

import pytest


@pytest.mark.parametrize(
    "start_method",
    [
        "spawn",
        "forkserver",
        "fork",
    ],
)
@pytest.mark.wandb_core_only
def test_share_child_base_spawn(user, start_method, relay_server, execute_script):
    with relay_server() as relay:
        script_path = pathlib.Path(__file__).parent / "share_child_base.py"
        execute_script(script_path, "--start-method", start_method)

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1

        run_id = run_ids[0]
        history = relay.context.get_run_history(run_id)
        assert len(history["s1"]) == 2
        assert history["s1"].tolist() == [11, 21]

        config = relay.context.get_run_config(run_id)
        assert config["c1"]["value"] == 11
        assert config["c2"]["value"] == 22
