from __future__ import annotations

import importlib
import inspect
import sys
from contextlib import contextmanager

import click
import pytest
from click.testing import CliRunner
from wandb.cli import beta_sandbox, cli

if sys.version_info < (3, 11):
    pytest.skip("wandb.sandbox requires Python 3.11+", allow_module_level=True)

pytest.importorskip("cwsandbox")
pytest.importorskip("cwsandbox.cli")


def make_cli_runner() -> CliRunner:
    """Makes a CliRunner instance that captures stderr separately in click<8.2."""
    runner_kwargs = {}
    if "mix_stderr" in inspect.signature(CliRunner.__init__).parameters:
        runner_kwargs["mix_stderr"] = False
    return CliRunner(**runner_kwargs)


def _fake_cwsandbox_cli() -> click.Group:
    @click.group()
    def sandbox() -> None:
        """Fake CWSandbox CLI."""

    @sandbox.command("ls")
    @click.option("--status", default=None)
    def list_sandboxes(status: str | None) -> None:
        click.echo(f"ls:{status}")

    @sandbox.command("logs")
    def logs() -> None:
        click.echo("logs")

    @sandbox.command("exec")
    def exec_command() -> None:
        click.echo("exec")

    @sandbox.command("sh")
    def shell() -> None:
        click.echo("sh")

    return sandbox


def test_sandbox_help_lists_upstream_subcommands(monkeypatch) -> None:
    monkeypatch.setattr(
        beta_sandbox.SandboxGroup,
        "_load_cwsandbox_cli",
        lambda self: _fake_cwsandbox_cli(),
    )

    result = make_cli_runner().invoke(cli.beta, ["sandbox", "--help"])

    assert result.exit_code == 0, result.output
    assert "ls" in result.output
    assert "logs" in result.output
    assert "exec" in result.output
    assert "sh" in result.output


def test_sandbox_command_passes_entity_override(monkeypatch) -> None:
    captured: list[str | None] = []
    sandbox_auth = importlib.import_module("wandb.sandbox._auth")

    @contextmanager
    def fake_override(entity: str | None):
        captured.append(entity)
        yield

    monkeypatch.setattr(
        beta_sandbox.SandboxGroup,
        "_load_cwsandbox_cli",
        lambda self: _fake_cwsandbox_cli(),
    )
    monkeypatch.setattr(sandbox_auth, "_override_sandbox_entity", fake_override)

    result = make_cli_runner().invoke(
        cli.beta,
        ["sandbox", "ls", "--entity", "team-override", "--status", "running"],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "ls:running"
    assert captured == ["team-override"]


def test_load_cwsandbox_cli_prints_install_hint(monkeypatch) -> None:
    def fake_import_module(name: str):
        raise ImportError(f"missing {name}")

    monkeypatch.setattr(beta_sandbox.importlib, "import_module", fake_import_module)
    group = beta_sandbox.SandboxGroup(name="sandbox")

    with pytest.raises(click.ClickException, match=r"wandb\[sandbox\]"):
        group._load_cwsandbox_cli()


def test_load_cwsandbox_cli_requires_python_3_11(monkeypatch) -> None:
    monkeypatch.setattr(beta_sandbox.sys, "version_info", (3, 10, 0))
    group = beta_sandbox.SandboxGroup(name="sandbox")

    with pytest.raises(click.ClickException, match=r"Python 3\.11 or newer"):
        group._load_cwsandbox_cli()
