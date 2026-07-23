import os

import pytest
import wandb
from click.testing import CliRunner
from wandb.cli import cli
from wandb.cli.clean import clean


@pytest.mark.usefixtures("user")  # for syncing and the online run
def test_cleans_expected_runs(runner: CliRunner):
    """An integration test for wandb clean, wandb sync and online logging."""
    with wandb.init(mode="offline") as unsynced_run:
        pass
    with wandb.init(mode="online") as online_run:
        pass
    with wandb.init(mode="offline") as synced_run:
        pass
    runner.invoke(cli.sync, synced_run.settings.sync_dir)

    result = runner.invoke(clean, ["--min-hours", "0"], input="y")

    assert os.path.exists(unsynced_run.settings.sync_dir)
    assert not os.path.exists(synced_run.settings.sync_dir)
    assert not os.path.exists(online_run.settings.sync_dir)
    assert "Found 2 run(s) to clean." in result.output
    assert online_run.id in result.output
    assert synced_run.id in result.output
    assert unsynced_run.id not in result.output
