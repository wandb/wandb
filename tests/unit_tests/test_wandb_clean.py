import pathlib
from typing import NoReturn

import pytest
from click.testing import CliRunner
from wandb.cli.clean import clean


@pytest.fixture
def wandb_dir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> pathlib.Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WANDB_DIR", str(tmp_path))
    return tmp_path


def _mkrun(path: pathlib.Path, synced: bool = False) -> None:
    path.mkdir(parents=True)
    if synced:
        (path / "run.wandb.synced").touch()


@pytest.mark.usefixtures("wandb_dir")
def test_empty_wandb_dir(runner: CliRunner):
    result = runner.invoke(clean)

    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "wandb: ERROR No wandb directory found.",
    ]


def test_bad_wandb_dir(wandb_dir: pathlib.Path, runner: CliRunner):
    (wandb_dir / "wandb").touch()

    result = runner.invoke(clean)

    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "wandb: ERROR Not a directory: 'wandb'",
    ]


def test_counts_unsynced_runs(wandb_dir: pathlib.Path, runner: CliRunner):
    wb = wandb_dir / "wandb"
    _mkrun(wb / "offline-run-20260101_010101-abc")
    _mkrun(wb / "offline-run-20260101_202020-xyz")

    result = runner.invoke(clean)

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "wandb: Found no synced runs, 2 unsynced.",
    ]


def test_finds_synced_runs(wandb_dir: pathlib.Path, runner: CliRunner):
    wb = wandb_dir / "wandb"
    _mkrun(wb / "offline-run-20260101_010101-1")
    _mkrun(wb / "offline-run-20260101_202020-2")
    _mkrun(wb / "offline-run-20260101_333000-3", synced=True)
    _mkrun(wb / "run-20260101_000444-4")

    result = runner.invoke(clean, input="y")
    lines = result.output.splitlines()

    assert result.exit_code == 0
    assert lines[0] == "wandb: Found 2 synced run(s)."
    assert set(lines[1:3]) == set(
        [
            "wandb:   wandb/offline-run-20260101_333000-3",
            "wandb:   wandb/run-20260101_000444-4",
        ]
    )
    assert lines[3] == "wandb: Are you sure you want to remove 2 run(s)? [y/n] y"


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

    result = runner.invoke(clean, input="y")

    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "wandb: Found 1 synced run(s).",
        "wandb:   wandb/run-20260101-123456-abc",
        "wandb: Are you sure you want to remove 1 run(s)? [y/n] y",
        "wandb: ERROR Failed to remove 'wandb/run-20260101-123456-abc': something went wrong",
    ]
