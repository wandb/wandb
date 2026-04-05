from __future__ import annotations

import sys

import pytest
from click.testing import CliRunner
from wandb.cli import cli

if sys.version_info < (3, 11):
    pytest.skip("wandb.sandbox requires Python 3.11+", allow_module_level=True)

import cwsandbox.cli.list as cwsandbox_list
from cwsandbox.exceptions import CWSandboxError


def test_sandbox_subcommands() -> None:
    result = CliRunner().invoke(cli.beta, ["sandbox", "--help"])

    expected_commands = {"ls", "logs", "exec", "sh"}
    missing = [cmd for cmd in expected_commands if cmd not in result.output]

    assert result.exit_code == 0, result.output
    assert not missing, f"Missing commands: {missing}"


def test_sandbox_ls_add_entity() -> None:
    result = CliRunner().invoke(cli.beta, ["sandbox", "ls", "--help"])

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


def test_sandbox_command_converts_cwsandbox_error(monkeypatch) -> None:
    def fake_list(cls, **kwargs):
        raise CWSandboxError("boom")

    monkeypatch.setattr(cwsandbox_list.Sandbox, "list", classmethod(fake_list))

    result = CliRunner().invoke(cli.beta, ["sandbox", "ls"])

    assert result.exit_code != 0
    assert "Error: boom" in result.output
