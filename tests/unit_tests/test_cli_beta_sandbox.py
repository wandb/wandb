from __future__ import annotations

import inspect
import sys
import types
from contextlib import contextmanager

import click
import pytest
from click.testing import CliRunner
from wandb.cli import beta_sandbox, cli


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

    @contextmanager
    def fake_override(entity: str | None):
        captured.append(entity)
        yield

    fake_sandbox_package = types.ModuleType("wandb.sandbox")
    fake_sandbox_package.__path__ = []
    fake_auth_module = types.ModuleType("wandb.sandbox._auth")
    fake_auth_module._override_sandbox_entity = fake_override
    fake_cwsandbox_package = types.ModuleType("cwsandbox")
    fake_cwsandbox_package.__path__ = []
    fake_exceptions_module = types.ModuleType("cwsandbox.exceptions")
    fake_exceptions_module.CWSandboxError = RuntimeError

    monkeypatch.setitem(sys.modules, "wandb.sandbox", fake_sandbox_package)
    monkeypatch.setitem(sys.modules, "wandb.sandbox._auth", fake_auth_module)
    monkeypatch.setitem(sys.modules, "cwsandbox", fake_cwsandbox_package)
    monkeypatch.setitem(sys.modules, "cwsandbox.exceptions", fake_exceptions_module)

    monkeypatch.setattr(
        beta_sandbox.SandboxGroup,
        "_load_cwsandbox_cli",
        lambda self: _fake_cwsandbox_cli(),
    )

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
