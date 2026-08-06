import pytest
from wandb.cli import cli


@pytest.fixture(autouse=True)
def _clear_cli_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset cli._api before each test.

    CliRunner invokes CLI commands in-process, so the module-level cache at
    cli._api survives across tests. A real CLI invocation gets a fresh
    process (and a fresh InternalApi); the autouse fixture mimics that so
    one test's cached client can't be reused by the next with a service
    connection that has since been torn down.
    """
    monkeypatch.setattr(cli, "_api", None)
