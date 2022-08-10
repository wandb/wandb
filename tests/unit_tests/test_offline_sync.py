import unittest.mock

import pytest
from wandb.cli import cli
from wandb.util import generate_id


@pytest.mark.flaky
@pytest.mark.xfail(reason="flaky test")
def test_sync_with_tensorboard(relay_server, runner, copy_asset, user):
    with unittest.mock.patch.dict("os.environ", {"WANDB_MODE": "offline"}):
        tf_event = copy_asset("events.out.tfevents.1585769947.cvp")
        run_id = generate_id()
        with relay_server() as relay:
            result = runner.invoke(cli.sync, [tf_event, f"--id={run_id}"])
    assert result.exit_code == 0
    history = relay.context.get_run_history(run_id, include_private=True)
    assert history["_runtime"][0] == 0
    assert all(history["_runtime"][1:])
