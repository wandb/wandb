from __future__ import annotations

import inspect
from dataclasses import dataclass

from click.testing import CliRunner
from wandb import env as wandb_env
from wandb.cli import beta_core, cli
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib.service import service_token


def make_cli_runner() -> CliRunner:
    """Makes a CliRunner instance that captures stderr separately in click<8.2.

    TODO: remove once python 3.9 support is dropped.
    """
    runner_kwargs = {}
    if "mix_stderr" in inspect.signature(CliRunner.__init__).parameters:
        runner_kwargs["mix_stderr"] = False
    return CliRunner(**runner_kwargs)


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


def test_core_start_prints_service_value(monkeypatch) -> None:
    token = service_token.UnixServiceToken(parent_pid=123, path="/tmp/wandb.sock")
    captured: dict[str, str] = {}

    def fake_start_detached(settings, *, idle_timeout: str):
        _ = settings
        captured["idle_timeout"] = idle_timeout
        return _FakeProc(token=token)

    monkeypatch.setattr(
        beta_core.service_process,
        "start_detached",
        fake_start_detached,
    )

    result = make_cli_runner().invoke(cli.beta, ["core", "start"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == token.env_value
    assert "Started detached wandb-core service." in result.stderr
    assert captured["idle_timeout"] == beta_core.DEFAULT_IDLE_TIMEOUT


def test_core_stop_sends_teardown_and_clears_env(monkeypatch) -> None:
    client = _FakeClient()
    token = _FakeToken(client)

    monkeypatch.setattr(beta_core.service_token, "from_env", lambda: token)

    cleared = {"called": False}

    def fake_clear() -> None:
        cleared["called"] = True

    monkeypatch.setattr(beta_core.service_token, "clear_service_in_env", fake_clear)

    result = make_cli_runner().invoke(cli.beta, ["core", "stop"])

    assert result.exit_code == 0
    assert f"Clear {wandb_env.SERVICE}" in result.output
    assert cleared["called"] is True
    assert client.closed is True

    assert len(client.published) == 1
    req = client.published[0]
    assert req.HasField("inform_teardown")
    assert req.inform_teardown.exit_code == 0
