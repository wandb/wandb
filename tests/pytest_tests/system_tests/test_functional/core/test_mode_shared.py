import pathlib

import pytest


@pytest.mark.skip(reason="TODO: Need to debug.")
@pytest.mark.wandb_core_only
def test_mode_shared(user, relay_server, copy_asset, execute_script):
    # copy assets to test directory:
    base_path = pathlib.Path(__file__).parent
    (base_path / pathlib.Path("scripts")).mkdir()
    (base_path / pathlib.Path(".wandb")).mkdir()
    for script in ("train.py", "eval.py"):
        copy_asset(base_path / "scripts" / script)

    # # Run the script with the specified globals
    path = str(pathlib.Path("scripts") / "train.py")
    with relay_server() as relay:
        execute_script(path)
        run_history = relay.context.history
        # 10 train steps + 2 eval steps
        assert len(run_history) == 12
        # one _client_id from the train script and two
        # from the two invocations of the eval script
        assert len(set(run_history["_client_id"])) == 3
