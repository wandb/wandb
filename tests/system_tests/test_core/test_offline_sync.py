import unittest.mock

import pytest
import wandb
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


@pytest.mark.parametrize(
    ("resume", "expect_warning"),
    [("must", True), (None, False)],
)
def test_legacy_sync_ignores_offline_resume(
    wandb_backend_spy,
    runner,
    resume,
    expect_warning,
):
    """Legacy sync warns that it cannot honor an offline resume intent."""
    with wandb.init(mode="offline", resume=resume) as run:
        run.log({"x": 1})

    result = runner.invoke(cli.sync, [run.settings.sync_dir, "--legacy"])

    assert result.exit_code == 0
    assert ("Ignoring offline resume intent" in result.output) is expect_warning

    # The run still syncs; the resume intent is dropped, not fatal.
    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.history(run_id=run.id)[0]["x"] == 1
