import pathlib
from datetime import datetime
from typing import NoReturn

import pytest
from click.testing import CliRunner
from wandb.cli import clean


@pytest.fixture
def wandb_dir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> pathlib.Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WANDB_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def now_20260805_3pm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        clean,
        "_DATETIME_NOW",
        lambda: datetime(2026, 8, 5, 15, 0, 0),
    )


def _mkrun(path: pathlib.Path, synced: bool = False) -> None:
    path.mkdir(parents=True)
    if synced:
        (path / "run.wandb.synced").touch()


@pytest.mark.usefixtures("wandb_dir")
def test_empty_wandb_dir(runner: CliRunner):
    result = runner.invoke(clean.clean)

    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "wandb: ERROR No wandb directory found.",
    ]


def test_bad_wandb_dir(wandb_dir: pathlib.Path, runner: CliRunner):
    (wandb_dir / "wandb").touch()

    result = runner.invoke(clean.clean)

    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "wandb: ERROR Not a directory: 'wandb'",
    ]


@pytest.mark.usefixtures("now_20260805_3pm")
def test_counts_skipped_runs(wandb_dir: pathlib.Path, runner: CliRunner):
    wb = wandb_dir / "wandb"
    _mkrun(wb / "offline-run-20260101_010101-unsynced1")
    _mkrun(wb / "offline-run-20260101_202020-unsynced2")
    _mkrun(wb / "run-20260805_140000-1hour")
    _mkrun(wb / "run-20260805_120000-3hours")

    result = runner.invoke(clean.clean, ["--min-hours", "2"], input="n")

    assert result.output.splitlines()[:3] == [
        "wandb: Skipping 1 run(s) created fewer than 2 hours ago.",
        "wandb: Skipping 2 unsynced run(s).",
        "wandb: Found 1 synced run(s).",
    ]


def test_finds_synced_runs(wandb_dir: pathlib.Path, runner: CliRunner):
    wb = wandb_dir / "wandb"
    _mkrun(wb / "offline-run-20260101_010101-1")
    _mkrun(wb / "offline-run-20260101_202020-2")
    _mkrun(wb / "offline-run-20260101_333000-3", synced=True)
    _mkrun(wb / "run-20260101_000444-4")

    result = runner.invoke(clean.clean, input="y")
    lines = result.output.splitlines()

    assert result.exit_code == 0
    assert lines[0] == "wandb: Skipping 2 unsynced run(s)."
    assert lines[1] == "wandb: Found 2 synced run(s)."
    assert set(lines[2:4]) == set(
        [
            "wandb:   wandb/offline-run-20260101_333000-3",
            "wandb:   wandb/run-20260101_000444-4",
        ]
    )
    assert lines[4] == "wandb: Are you sure you want to remove 2 run(s)? [y/n] y"


def test_reports_rmtree_errors(
    wandb_dir: pathlib.Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
):
    def raise_os_error(*args, **kwargs) -> NoReturn:
        err = OSError()
        err.strerror = "something went wrong"
        raise err

    _mkrun(wandb_dir / "wandb" / "run-20260101-123456-abc")
    monkeypatch.setattr("shutil.rmtree", raise_os_error)

    result = runner.invoke(clean.clean, input="y")

    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "wandb: Found 1 synced run(s).",
        "wandb:   wandb/run-20260101-123456-abc",
        "wandb: Are you sure you want to remove 1 run(s)? [y/n] y",
        "wandb: ERROR Failed to remove 'wandb/run-20260101-123456-abc': something went wrong",
    ]
