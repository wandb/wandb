from __future__ import annotations

import cwsandbox.cli.list as cwsandbox_list
from click.testing import CliRunner
from wandb.cli import cli
from wandb.sandbox import CWSandboxError


def test_sandbox_command_converts_cwsandbox_error(monkeypatch) -> None:
    def fake_list(cls, **kwargs):
        raise CWSandboxError("boom")

    monkeypatch.setattr(cwsandbox_list.Sandbox, "list", classmethod(fake_list))

    result = CliRunner().invoke(cli.beta, ["sandbox", "ls"])

    assert result.exit_code != 0
    assert "Error: boom" in result.output
