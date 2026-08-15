from __future__ import annotations

import pytest
from click.testing import CliRunner
from wandb.cli import cli

from tests.fixtures.wandb_backend_spy import WandbBackendSpy


@pytest.mark.parametrize("legacy", (False, True))
def test_sync_compat_log_old_auto_steps(
    wandb_backend_spy: WandbBackendSpy,
    runner: CliRunner,
    copy_asset,
    legacy: bool,
):
    """Sync a pinned old-format golden fixture through the full CLI path."""
    run_dir = copy_asset("compat_logs/offline-run-old_auto_steps")

    args = ["sync", str(run_dir)]
    if legacy:
        args.append("--legacy")

    result = runner.invoke(cli.beta, args)
    assert result.exit_code == 0

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id="old_auto_steps")
        assert {row["_step"] for row in history.values()} == {0, 1, 2}
