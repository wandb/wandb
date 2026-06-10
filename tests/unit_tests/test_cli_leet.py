from __future__ import annotations

import pathlib

import pytest
from wandb.cli import cli, leet


@pytest.fixture
def core_calls(monkeypatch) -> list[list[str]]:
    """Stub out wandb-core and record the arguments it would be invoked with."""
    calls: list[list[str]] = []

    monkeypatch.setattr(leet, "get_core_path", lambda: "wandb-core")
    monkeypatch.setattr(leet, "error_reporting_enabled", lambda: True)
    monkeypatch.setattr(leet, "is_debug", lambda default: False)
    monkeypatch.setattr(leet, "_run_core", lambda args, env=None: calls.append(args))

    return calls


def test_leet_help_shows_run_command(runner):
    result = runner.invoke(cli.cli, ["leet", "--help"])

    assert result.exit_code == 0
    assert "Launch the LEET TUI" in result.output


def test_leet_defaults_to_run_command(runner, core_calls, tmp_path: pathlib.Path):
    wandb_dir = tmp_path / "wandb"
    wandb_dir.mkdir()

    result = runner.invoke(cli.cli, ["leet", str(wandb_dir)])

    assert result.exit_code == 0
    assert core_calls == [["wandb-core", "leet", str(wandb_dir.resolve())]]


def test_leet_resolves_run_directory(runner, core_calls, tmp_path: pathlib.Path):
    run_dir = tmp_path / "wandb" / "run-20250101_000000-abc123"
    run_dir.mkdir(parents=True)
    run_file = run_dir / "run-abc123.wandb"
    run_file.touch()

    result = runner.invoke(cli.cli, ["leet", str(run_dir)])

    assert result.exit_code == 0
    assert core_calls == [
        [
            "wandb-core",
            "leet",
            "--run-file",
            str(run_file.resolve()),
            str((tmp_path / "wandb").resolve()),
        ]
    ]


def test_beta_leet_is_an_alias(runner, core_calls, tmp_path: pathlib.Path):
    wandb_dir = tmp_path / "wandb"
    wandb_dir.mkdir()

    result = runner.invoke(cli.cli, ["beta", "leet", str(wandb_dir)])

    assert result.exit_code == 0
    assert "generally available as `wandb leet`" in result.stderr
    assert core_calls == [["wandb-core", "leet", str(wandb_dir.resolve())]]
