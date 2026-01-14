import unittest.mock

import pytest
from wandb.cli import cli
from wandb.sdk.lib.runid import generate_id


@pytest.mark.flaky
def test_sync_with_tensorboard(wandb_backend_spy, runner, copy_asset):
    run_id = generate_id()
    with unittest.mock.patch.dict("os.environ", {"WANDB_MODE": "offline"}):
        tf_event = copy_asset("events.out.tfevents.1585769947.cvp")
        result = runner.invoke(cli.sync, [tf_event, f"--id={run_id}"])
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run_id)
        assert history[0]["_runtime"] == 0
        history_runtime_values = [v["_runtime"] for k, v in history.items() if k > 0]
        for value in history_runtime_values:
            assert value > 0
