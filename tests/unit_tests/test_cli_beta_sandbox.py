from __future__ import annotations

import importlib
import inspect
import sys
import types
from contextlib import contextmanager

import pytest
from click.testing import CliRunner
from wandb.cli import beta_sandbox, cli

if sys.version_info < (3, 11):
    pytest.skip("wandb.sandbox requires Python 3.11+", allow_module_level=True)

import cwsandbox.cli.list as cwsandbox_list
from cwsandbox.exceptions import CWSandboxError


def make_cli_runner() -> CliRunner:
    """Makes a CliRunner instance that captures stderr separately in click<8.2."""
    runner_kwargs = {}
    if "mix_stderr" in inspect.signature(CliRunner.__init__).parameters:
        runner_kwargs["mix_stderr"] = False
    return CliRunner(**runner_kwargs)


@pytest.fixture(autouse=True)
def reset_sandbox_group_cache():
    sandbox_group = cli.beta.commands["sandbox"]
    assert isinstance(sandbox_group, beta_sandbox.SandboxGroup)
    sandbox_group._base_cli = None
    sandbox_group._wrapped_commands = {}
    yield
    sandbox_group._base_cli = None
    sandbox_group._wrapped_commands = {}


def test_sandbox_help_lists_real_upstream_subcommands() -> None:
    result = make_cli_runner().invoke(cli.beta, ["sandbox", "--help"])

    expected_commands = {"ls", "logs", "exec", "sh"}
    missing = [cmd for cmd in expected_commands if cmd not in result.output]

    assert result.exit_code == 0, result.output
    assert not missing, f"Missing commands: {missing}"


def test_sandbox_ls_help_includes_entity_and_upstream_options() -> None:
    result = make_cli_runner().invoke(cli.beta, ["sandbox", "ls", "--help"])

    expected_flags = {
        "--entity",
        "--status",
        "--tag",
        "--runway-id",
        "--tower-id",
        "--output",
    }

    missing = [f for f in expected_flags if f not in result.output]
    assert not missing, f"Missing flags: {missing}"


def test_sandbox_command_passes_entity_override_to_real_ls_command(monkeypatch) -> None:
    captured: list[str | None] = []
    list_calls: list[dict[str, object | None]] = []
    sandbox_auth = importlib.import_module("wandb.sandbox._auth")

    @contextmanager
    def fake_override(entity: str | None):
        captured.append(entity)
        yield

    def fake_list(cls, **kwargs):
        list_calls.append(kwargs)
        return types.SimpleNamespace(result=lambda: [])

    monkeypatch.setattr(sandbox_auth, "_override_sandbox_entity", fake_override)
    monkeypatch.setattr(cwsandbox_list.Sandbox, "list", classmethod(fake_list))

    result = make_cli_runner().invoke(
        cli.beta,
        ["sandbox", "ls", "--entity", "team-override", "--status", "running"],
    )

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "No sandboxes found."
    assert captured == ["team-override"]
    assert list_calls == [
        {
            "tags": None,
            "status": "running",
            "runway_ids": None,
            "tower_ids": None,
        }
    ]


def test_sandbox_command_converts_cwsandbox_error(monkeypatch) -> None:
    def fake_list(cls, **kwargs):
        raise CWSandboxError("boom")

    monkeypatch.setattr(cwsandbox_list.Sandbox, "list", classmethod(fake_list))

    result = make_cli_runner().invoke(cli.beta, ["sandbox", "ls"])

    assert result.exit_code != 0
    assert "Error: boom" in result.output
