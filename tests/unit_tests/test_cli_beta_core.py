from __future__ import annotations

from dataclasses import dataclass

import pytest
from click.testing import CliRunner
from wandb import env as wandb_env
from wandb.cli import beta_core, cli
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib.service import service_token


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@dataclass
class _FakeProc:
    token: service_token.ServiceToken


class _FakeClient:
    def __init__(self) -> None:
        self.published: list[spb.ServerRequest] = []
        self.closed = False

    async def publish(self, req: spb.ServerRequest) -> None:
        self.published.append(req)

    async def close(self) -> None:
        self.closed = True


class _FakeToken:
    def __init__(self, client: _FakeClient) -> None:
        self._client = client

    def connect(self, *, asyncer) -> _FakeClient:
        _ = asyncer
        return self._client


def test_core_start_print_posix(monkeypatch: pytest.MonkeyPatch, runner: CliRunner):
    token = service_token.UnixServiceToken(parent_pid=123, path="/tmp/wandb.sock")

    def fake_start_detached(settings, *, idle_timeout_seconds: int):
        _ = settings, idle_timeout_seconds
        return _FakeProc(token=token)

    monkeypatch.setattr(
        beta_core.service_process, "start_detached", fake_start_detached
    )

    result = runner.invoke(cli.beta, "core start --print")

    assert result.exit_code == 0
    assert result.output.strip() == (
        f"export {wandb_env.SERVICE}={token._as_env_string()}"
    )


def test_core_stop_print_unsets_and_sends_teardown(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
):
    client = _FakeClient()
    token = _FakeToken(client)

    monkeypatch.setattr(beta_core.service_token, "from_env", lambda: token)

    cleared = {"called": False}

    def fake_clear() -> None:
        cleared["called"] = True

    monkeypatch.setattr(beta_core.service_token, "clear_service_in_env", fake_clear)

    result = runner.invoke(cli.beta, "core stop --print")

    assert result.exit_code == 0
    assert result.output.strip() == f"unset {wandb_env.SERVICE}"

    assert cleared["called"] is True
    assert client.closed is True

    assert len(client.published) == 1
    req = client.published[0]
    assert req.HasField("inform_teardown")
    assert req.inform_teardown.exit_code == 0
