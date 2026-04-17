from __future__ import annotations

import cwsandbox.cli.list as cwsandbox_list
import pytest
from click.testing import CliRunner
from wandb.cli import cli
from wandb.sandbox import CWSandboxError


@pytest.mark.parametrize(
    ("argv", "expected_strings"),
    [
        (
            ["sandbox", "--help"],
            ["ls", "sh", "exec", "logs", "--entity", "wandb beta sandbox ls"],
        ),
        (
            ["sandbox", "ls", "--help"],
            ["--entity", "--status", "--tag", "--output", "wandb beta sandbox ls"],
        ),
        (
            ["sandbox", "sh", "--help"],
            ["--entity", "SANDBOX_ID", "--cmd", "wandb beta sandbox sh"],
        ),
        (
            ["sandbox", "exec", "--help"],
            [
                "--entity",
                "SANDBOX_ID",
                "COMMAND_ARGS...",
                "--cwd",
                "--timeout",
                "wandb beta sandbox exec",
            ],
        ),
        (
            ["sandbox", "logs", "--help"],
            [
                "--entity",
                "SANDBOX_ID",
                "--follow",
                "--tail",
                "--since",
                "--timestamps",
                "wandb beta sandbox logs",
            ],
        ),
    ],
)
def test_sandbox_help_text(
    argv: list[str],
    expected_strings: list[str],
) -> None:
    result = CliRunner().invoke(cli.beta, argv)

    assert result.exit_code == 0, result.output
    assert "wandb beta sandbox" in result.output
    assert "cwsandbox" not in result.output
    for expected in expected_strings:
        assert expected in result.output


def test_sandbox_command_converts_cwsandbox_error(monkeypatch) -> None:
    def fake_list(cls, **kwargs):
        raise CWSandboxError("boom")

    monkeypatch.setattr(cwsandbox_list.Sandbox, "list", classmethod(fake_list))

    result = CliRunner().invoke(cli.beta, ["sandbox", "ls"])

    assert result.exit_code != 0
    assert "Error: boom" in result.output
