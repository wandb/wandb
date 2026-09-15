from __future__ import annotations

import pathlib

import pytest
from wandb.cli import cli, leet
from wandb.errors import WandbCoreNotAvailableError

_BASE_URL = "https://api.wandb.ai"


@pytest.fixture
def core_calls(monkeypatch) -> list[list[str]]:
    """Stub out wandb-core and record the arguments it would be invoked with."""
    calls: list[list[str]] = []

    class _StubSettings:
        base_url = _BASE_URL
        _offline = False
        _noop = False

    class _StubSingleton:
        settings = _StubSettings()

    monkeypatch.setattr(leet, "get_core_path", lambda: "wandb-core")
    monkeypatch.setattr(leet, "error_reporting_enabled", lambda: True)
    monkeypatch.setattr(leet, "is_debug", lambda default: False)
    monkeypatch.setattr(leet, "_run_core", lambda args, env=None: calls.append(args))
    monkeypatch.setattr(leet.wandb_setup, "singleton", lambda: _StubSingleton())

    return calls


@pytest.fixture
def core_unavailable(monkeypatch) -> None:
    """Make wandb-core resolution fail as on an unsupported platform."""

    def raise_unavailable() -> str:
        raise WandbCoreNotAvailableError("wandb-core not found")

    monkeypatch.setattr(leet, "get_core_path", raise_unavailable)


@pytest.mark.parametrize("help_flag", ["--help", "-h"])
def test_leet_help_shows_group_help(runner, core_unavailable, help_flag):
    """Group help lists all subcommands and works without wandb-core."""
    result = runner.invoke(cli.cli, ["leet", help_flag])

    assert result.exit_code == 0
    assert "Lightweight Experiment Exploration Tool" in result.output
    assert "Launch the LEET TUI" in result.output
    assert "Launch the standalone system monitor" in result.output
    assert "Edit LEET configuration" in result.output
    assert "Browse the raw records" in result.output
    assert "wandb-core not found" not in result.output


def test_leet_run_help_shows_run_command(runner):
    result = runner.invoke(cli.cli, ["leet", "run", "--help"])

    assert result.exit_code == 0
    assert "Launch the LEET TUI" in result.output


def test_leet_fails_cleanly_without_core(runner, core_unavailable, tmp_path):
    wandb_dir = tmp_path / "wandb"
    wandb_dir.mkdir()

    result = runner.invoke(cli.cli, ["leet", str(wandb_dir)])

    assert result.exit_code == 1
    assert "Error: wandb-core not found" in result.stderr


def test_leet_defaults_to_run_command(runner, core_calls, tmp_path: pathlib.Path):
    wandb_dir = tmp_path / "wandb"
    wandb_dir.mkdir()

    result = runner.invoke(cli.cli, ["leet", str(wandb_dir)])

    assert result.exit_code == 0
    assert core_calls == [
        ["wandb-core", "leet", "--base-url", _BASE_URL, str(wandb_dir.resolve())]
    ]


@pytest.mark.parametrize("mode_attr", ["_offline", "_noop"])
def test_leet_offline_disables_telemetry(
    runner, core_calls, tmp_path: pathlib.Path, mode_attr: str
):
    wandb_dir = tmp_path / "wandb"
    wandb_dir.mkdir()
    setattr(leet.wandb_setup.singleton().settings, mode_attr, True)

    result = runner.invoke(cli.cli, ["leet", str(wandb_dir)])

    assert result.exit_code == 0
    assert core_calls == [
        ["wandb-core", "leet", "--no-observability", str(wandb_dir.resolve())]
    ]


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
            "--base-url",
            _BASE_URL,
            "--run-file",
            str(run_file.resolve()),
            str((tmp_path / "wandb").resolve()),
        ]
    ]


def test_leet_inspect_resolves_run_directory(
    runner, core_calls, tmp_path: pathlib.Path
):
    run_dir = tmp_path / "wandb" / "run-20250101_000000-abc123"
    run_dir.mkdir(parents=True)
    run_file = run_dir / "run-abc123.wandb"
    run_file.touch()

    result = runner.invoke(cli.cli, ["leet", "inspect", str(run_dir)])

    assert result.exit_code == 0
    assert core_calls == [
        [
            "wandb-core",
            "leet",
            "--base-url",
            _BASE_URL,
            "--inspect",
            "--run-file",
            str(run_file.resolve()),
            str((tmp_path / "wandb").resolve()),
        ]
    ]


def test_leet_inspect_wandb_dir_uses_latest_run(
    runner, core_calls, tmp_path: pathlib.Path
):
    wandb_dir = tmp_path / "wandb"
    wandb_dir.mkdir()

    result = runner.invoke(cli.cli, ["leet", "inspect", str(wandb_dir)])

    assert result.exit_code == 0
    assert core_calls == [
        [
            "wandb-core",
            "leet",
            "--base-url",
            _BASE_URL,
            "--inspect",
            str(wandb_dir.resolve()),
        ]
    ]


def test_beta_leet_is_an_alias(runner, core_calls, tmp_path: pathlib.Path):
    wandb_dir = tmp_path / "wandb"
    wandb_dir.mkdir()

    result = runner.invoke(cli.cli, ["beta", "leet", str(wandb_dir)])

    assert result.exit_code == 0
    assert "generally available as `wandb leet`" in result.stderr
    assert core_calls == [
        ["wandb-core", "leet", "--base-url", _BASE_URL, str(wandb_dir.resolve())]
    ]


@pytest.mark.parametrize("host", ["forge.coreweave.com", "qa.forge.coreweave.com"])
@pytest.mark.parametrize("prefix", ["/wandb", "/api/wandb"])
@pytest.mark.parametrize("run_path", ["/entity/project/runs/id", "/entity/project/id/"])
def test_parse_forge_remote_url(host, prefix, run_path):
    base_url = f"https://{host}/api/wandb"

    assert leet._parse_remote_url(
        f"https://{host}{prefix}{run_path}?view=history#chart"
    ) == (base_url, base_url + run_path)


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://wandb.ai/entity/project/runs/id?view=history#chart",
            ("https://api.wandb.ai", "https://api.wandb.ai/entity/project/runs/id"),
        ),
        (
            "https://api.wandb.ai/entity/project/id",
            ("https://api.wandb.ai", "https://api.wandb.ai/entity/project/id"),
        ),
        (
            "http://localhost:8080/wandb/project/runs/id",
            ("http://localhost:8080", "http://localhost:8080/wandb/project/runs/id"),
        ),
    ],
)
def test_parse_remote_url_preserves_legacy_hosts(url, expected):
    assert leet._parse_remote_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://forge.coreweave.com/entity/project/runs/id",
        "https://forge.coreweave.com/wandb/entity/project/sweeps/id",
        "https://forge.coreweave.com/wandb/entity/project/runs/id/extra",
        "https://forge.coreweave.com/wandb/entity//runs/id",
        "https://forge.coreweave.com/wandb-other/entity/project/runs/id",
        "https://forge.coreweave.com/api/wandb-other/entity/project/runs/id",
        "http://forge.coreweave.com/wandb/entity/project/runs/id",
        "https://forge.coreweave.com:8443/wandb/entity/project/runs/id",
        "https://forge.coreweave.com.example.com/wandb/entity/project/runs/id",
        "https://example.com/api/wandb/entity/project/runs/id",
    ],
)
def test_parse_remote_url_rejects_invalid_forge_routes(url):
    with pytest.raises(SystemExit):
        leet._parse_remote_url(url)
