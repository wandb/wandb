from __future__ import annotations

import pathlib
import re

import pytest
import wandb
from click.testing import CliRunner
from wandb.cli import beta_sync, cli


def test_makes_sync_request(runner: CliRunner):
    with wandb.init(mode="offline") as run:
        run.log({"test_sync": 321})

    result = runner.invoke(cli.beta, f"sync {run.settings.sync_dir}")

    lines = result.output.splitlines()
    assert lines[0] == "Syncing 1 file(s):"
    assert lines[1].endswith(f"run-{run.id}.wandb")
    assert lines[2] == "wandb: ERROR Internal error: not implemented"


@pytest.mark.parametrize("skip_synced", (True, False))
def test_skip_synced(tmp_path, runner: CliRunner, skip_synced):
    (tmp_path / "run-1.wandb").touch()
    (tmp_path / "run-2.wandb").touch()
    (tmp_path / "run-2.wandb.synced").touch()
    (tmp_path / "run-3.wandb").touch()

    skip = "--skip-synced" if skip_synced else "--no-skip-synced"
    result = runner.invoke(cli.beta, f"sync --dry-run {skip} {tmp_path}")

    assert "run-1.wandb" in result.output
    assert "run-3.wandb" in result.output

    if skip_synced:
        assert "run-2.wandb" not in result.output
    else:
        assert "run-2.wandb" in result.output


def test_sync_wandb_file(tmp_path, runner: CliRunner):
    file = tmp_path / "run.wandb"
    file.touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {file}")

    lines = result.output.splitlines()
    assert lines[0] == "Would sync 1 file(s):"
    assert lines[1].endswith("run.wandb")


def test_sync_run_directory(tmp_path, runner: CliRunner):
    run_dir = tmp_path / "some-run"
    run_dir.mkdir()
    (run_dir / "run.wandb").touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {run_dir}")

    lines = result.output.splitlines()
    assert lines[0] == "Would sync 1 file(s):"
    assert lines[1].endswith("run.wandb")


def test_sync_wandb_directory(tmp_path, runner: CliRunner):
    wandb_dir = tmp_path / "wandb-dir"
    run1_dir = wandb_dir / "run-1"
    run2_dir = wandb_dir / "run-2"

    wandb_dir.mkdir()
    run1_dir.mkdir()
    run2_dir.mkdir()
    (run1_dir / "run-1.wandb").touch()
    (run2_dir / "run-2.wandb").touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {wandb_dir}")

    lines = result.output.splitlines()
    assert lines[0] == "Would sync 2 file(s):"
    assert lines[1].endswith("run-1.wandb")
    assert lines[2].endswith("run-2.wandb")


def test_truncates_printed_paths(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
):
    monkeypatch.setattr(beta_sync, "_MAX_LIST_LINES", 5)
    files = list((tmp_path / f"run-{i}.wandb") for i in range(20))
    for file in files:
        file.touch()

    result = runner.invoke(cli.beta, f"sync --dry-run {tmp_path}")

    lines = result.output.splitlines()
    assert lines[0] == "Would sync 20 file(s):"
    for line in lines[1:6]:
        assert re.fullmatch(r"  .+/run-\d+\.wandb", line)
    assert lines[6] == "  +15 more"
