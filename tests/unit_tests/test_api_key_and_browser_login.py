"""How API key logins interact with a stored browser login."""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.apis.public.service_api import ServiceApi
from wandb.cli import cli
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.lib import wbauth
from wandb.sdk.lib.wbauth import browser_login, prompt

from tests.unit_tests.test_lib.test_auth_browser_login import (
    FakeOAuthServer,
    make_token_set,
    serve_oauth,
)


@pytest.fixture
def oauth_server() -> Iterator[FakeOAuthServer]:
    with serve_oauth() as server:
        yield server


@pytest.fixture
def host(oauth_server: FakeOAuthServer) -> wbauth.HostUrl:
    return wbauth.HostUrl(oauth_server.host.url)


@pytest.fixture
def credentials_file() -> pathlib.Path:
    return pathlib.Path(wandb_setup.singleton().settings.credentials_file)


def token_exchanges(server: FakeOAuthServer) -> list[dict[str, str]]:
    return [request for request in server.received if request["path"] == "/oidc/token"]


def revoked_tokens(server: FakeOAuthServer) -> list[str]:
    return [
        request["token"]
        for request in server.received
        if request["path"] == "/oidc/revoke"
    ]


def stored_refresh_token(
    credentials_file: pathlib.Path,
    host: wbauth.HostUrl,
) -> str | None:
    tokens = browser_login.load_credentials(credentials_file, host)
    return tokens.refresh_token if tokens else None


@pytest.mark.parametrize(
    "extra_args",
    [
        pytest.param(["--relogin"], id="relogin"),
        pytest.param(["k" * 40], id="explicit-key"),
    ],
)
@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_api_key_login_discards_a_browser_login(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    extra_args: list[str],
):
    monkeypatch.setattr(prompt, "_prompt_api_key", lambda **kwargs: "k" * 40)
    browser_login.save_credentials(credentials_file, host, make_token_set())

    result = runner.invoke(cli.cli, ["login", "--host", host.url, *extra_args])

    assert result.exit_code == 0, result.output
    assert token_exchanges(oauth_server) == []
    assert stored_refresh_token(credentials_file, host) is None
    assert revoked_tokens(oauth_server) == ["wb_rt_stored"]


@pytest.mark.parametrize(
    "login_kwargs",
    [
        pytest.param({"key": "k" * 40}, id="explicit-key"),
        pytest.param({"relogin": True}, id="relogin"),
    ],
)
@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_python_login_discards_a_browser_login(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    login_kwargs: dict[str, object],
):
    """Python wandb.login(key=...) and wandb.login(relogin=True) persist to .netrc,
    so they also discard and revoke any stored browser login for the host.
    """
    monkeypatch.setattr(prompt, "_prompt_api_key", lambda **kwargs: "k" * 40)
    browser_login.save_credentials(credentials_file, host, make_token_set())

    assert wandb.login(host=host.url, **login_kwargs) is True

    assert stored_refresh_token(credentials_file, host) is None
    assert revoked_tokens(oauth_server) == ["wb_rt_stored"]


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_ephemeral_api_key_keeps_the_browser_login(
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    """Per-run keys (`update_api_key=False`) do not write .netrc or touch browser logins."""
    browser_login.save_credentials(credentials_file, host, make_token_set())

    logged_in, _ = wandb_login._login(
        key="k" * 40,
        host=host.url,
        update_api_key=False,
        verify=True,
    )

    assert logged_in is True
    assert stored_refresh_token(credentials_file, host) == "wb_rt_stored"
    assert revoked_tokens(oauth_server) == []


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_failed_netrc_write_keeps_the_browser_login(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    browser_login.save_credentials(credentials_file, host, make_token_set())
    monkeypatch.setattr(
        wbauth,
        "write_netrc_auth",
        MagicMock(side_effect=wbauth.WriteNetrcError("read-only netrc")),
    )

    assert wandb.login(host=host.url, key="k" * 40) is True

    assert stored_refresh_token(credentials_file, host) == "wb_rt_stored"
    assert revoked_tokens(oauth_server) == []


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_login_with_a_key_succeeds_when_revoking_fails(
    runner,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    browser_login.save_credentials(credentials_file, host, make_token_set())
    oauth_server.status = 500
    oauth_server.body = None

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "k" * 40])

    assert result.exit_code == 0, result.output
    assert "Could not revoke the previous browser login" in result.output
    assert stored_refresh_token(credentials_file, host) is None


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_login_with_a_key_warns_when_the_browser_login_cannot_be_removed(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    browser_login.save_credentials(credentials_file, host, make_token_set())

    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(pathlib.Path, "replace", deny)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "k" * 40])

    assert result.exit_code == 0, result.output
    assert "Could not remove the browser login" in result.output
    assert revoked_tokens(oauth_server) == []
    assert stored_refresh_token(credentials_file, host) == "wb_rt_stored"


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_login_with_a_key_leaves_the_credentials_file_alone_without_a_browser_login(
    runner,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    result = runner.invoke(cli.cli, ["login", "--host", host.url, "k" * 40])

    assert result.exit_code == 0, result.output
    assert not credentials_file.exists()


@pytest.mark.usefixtures("local_settings")
def test_rejected_api_key_keeps_the_browser_login(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    browser_login.save_credentials(credentials_file, host, make_token_set())
    monkeypatch.setattr(
        ServiceApi,
        "authenticate",
        MagicMock(side_effect=RuntimeError("rejected")),
    )

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "k" * 40])

    assert result.exit_code == 1, result.output
    assert stored_refresh_token(credentials_file, host) == "wb_rt_stored"
    assert revoked_tokens(oauth_server) == []


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_login_with_no_key_keeps_a_browser_login(
    runner,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    browser_login.save_credentials(credentials_file, host, make_token_set())

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--verify"])

    assert result.exit_code == 0, result.output
    assert stored_refresh_token(credentials_file, host) == "wb_rt_stored"
    assert revoked_tokens(oauth_server) == []
