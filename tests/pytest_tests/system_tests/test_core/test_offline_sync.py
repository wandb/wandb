import os
import unittest.mock

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.lib.runid import generate_id


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


@pytest.mark.parametrize("mark_synced", [True, False])
def test_beta_sync(wandb_init, runner, mark_synced):
    _ = pytest.importorskip("wandb_core")

    os.makedirs(".wandb", exist_ok=True)
    run = wandb_init(settings={"mode": "offline"})
    run.log(dict(a=1))
    run.finish()

    args = ["sync", ".wandb"]
    if not mark_synced:
        args.append("--no-mark-synced")
    result = runner.invoke(cli.beta, args)
    print(result.output)
    assert result.exit_code == 0
    assert f"{run.id}" in result.output

    if mark_synced:
        # check that f"{run.settings.sync_file}.synced" exists
        assert os.path.exists(f"{run.settings.sync_file}.synced")
    else:
        assert not os.path.exists(f"{run.settings.sync_file}.synced")


def test_beta_sync_two_runs(user, test_settings, runner):
    _ = pytest.importorskip("wandb_core")
    os.makedirs(".wandb", exist_ok=True)
    run = wandb.init(settings=test_settings({"mode": "offline"}))
    run.log(dict(a=1))
    run.finish()

    run2 = wandb.init(settings=test_settings({"mode": "offline"}))
    run2.log(dict(a=1))
    run2.finish()

    result = runner.invoke(cli.beta, ["sync", ".wandb"])
    print(result.output)
    assert result.exit_code == 0
    assert f"{run.id}" in result.output
    assert f"{run2.id}" in result.output
