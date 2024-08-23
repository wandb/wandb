import pytest


@pytest.mark.wandb_core_only
def test_mode_shared(user, relay_server, copy_asset):
    # copy assets to test directory:
    # pathlib.Path("scripts").mkdir()
    # pathlib.Path(".wandb").mkdir()
    # for script in ("train.py", "eval.py"):
    #     copy_asset(pathlib.Path("scripts") / script)

    # # # Run the script with the specified globals
    # path = str(pathlib.Path("scripts") / "train.py")
    # # clear argv
    # with mock.patch("sys.argv", [""]), relay_server() as relay:
    #     runpy.run_path(path, run_name="__main__")
    #     run_history = relay.context.history
    #     # 10 train steps + 2 eval steps
    #     assert len(run_history) == 12
    #     # one _client_id from the train script and two
    #     # from the two invocations of the eval script
    #     assert len(set(run_history["_client_id"])) == 3
    pass
