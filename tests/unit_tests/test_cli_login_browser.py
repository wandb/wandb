"""`wandb login --browser`, and how it interacts with API key logins."""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from wandb.apis.public.service_api import ServiceApi
from wandb.cli import cli
from wandb.errors import AuthenticationError
from wandb.sdk import wandb_setup
from wandb.sdk.lib import urls, wbauth
from wandb.sdk.lib.wbauth import browser_login

from tests.unit_tests.test_lib.test_auth_browser_login import (
    FakeOAuthServer,
    make_token_set,
    mock_browser_login,
    serve_oauth,
)


@pytest.fixture(autouse=True)
def browser_is_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the browser check so it does not depend on this machine."""
    monkeypatch.setattr(browser_login, "can_open_browser", lambda: True)


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


@pytest.fixture
def api_key_logins(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Record wandb.login() calls, which answer that the login succeeded."""
    calls: list[dict] = []

    def record_login(**kwargs: object) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr("wandb.login", record_login)
    return calls


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


@pytest.mark.usefixtures("local_settings")
def test_login_asks_for_an_api_key_by_default(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    api_key_logins: list[dict],
):
    mock_browser_login(monkeypatch)

    result = runner.invoke(cli.cli, ["login", "--host", host.url])

    assert result.exit_code == 0, result.output
    assert oauth_server.received == []
    [call] = api_key_logins
    assert call["key"] is None
    assert call["relogin"] is False


@pytest.mark.usefixtures("local_settings")
def test_relogin_replaces_a_browser_login_with_an_api_key(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    api_key_logins: list[dict],
):
    mock_browser_login(monkeypatch)
    browser_login.save_credentials(credentials_file, host, make_token_set())

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--relogin"])

    assert result.exit_code == 0, result.output
    assert token_exchanges(oauth_server) == []
    assert api_key_logins[-1]["relogin"] is True
    # The browser login would outrank the new API key, so it goes.
    assert stored_refresh_token(credentials_file, host) is None
    assert revoked_tokens(oauth_server) == ["wb_rt_stored"]


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_browser_flag_uses_the_browser(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    api_key_logins: list[dict],
):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_IDENTITY_TOKEN_FILE", raising=False)
    mock_browser_login(monkeypatch)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 0, result.output
    assert api_key_logins == []
    [exchange] = token_exchanges(oauth_server)
    assert exchange["grant_type"] == "authorization_code"
    assert stored_refresh_token(credentials_file, host) == "wb_rt_new"
    assert isinstance(
        wbauth.session_credentials(host=host),
        wbauth.AuthBrowserLogin,
    )
    assert "instead of the browser login" not in result.output


@pytest.mark.usefixtures("local_settings")
def test_browser_flag_gives_up_after_the_timeout(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    # A browser that never approves the login.
    monkeypatch.setattr(browser_login, "_open_browser", lambda url: True)
    monkeypatch.setattr(browser_login, "LOGIN_TIMEOUT_SECONDS", 0.1)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 1, result.output
    assert "Timed out waiting for the login" in result.output
    assert stored_refresh_token(credentials_file, host) is None


@pytest.mark.parametrize(
    "env_var, value",
    [
        ("WANDB_API_KEY", "k" * 40),
        ("WANDB_IDENTITY_TOKEN_FILE", "token.jwt"),
    ],
)
@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_browser_flag_warns_that_an_exported_credential_wins(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    env_var: str,
    value: str,
):
    """The browser login is stored, but runs keep using the export."""
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_IDENTITY_TOKEN_FILE", raising=False)
    monkeypatch.setenv(env_var, value)
    mock_browser_login(monkeypatch)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 0, result.output
    assert len(token_exchanges(oauth_server)) == 1
    assert f"{env_var} is set, so W&B uses it instead of the browser login" in (
        result.output
    )


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_browser_flag_reuses_the_stored_browser_login(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(monkeypatch)
    browser_login.save_credentials(credentials_file, host, make_token_set("wb_rt_old"))

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 0, result.output
    assert oauth_server.received == []
    assert "Already logged in" in result.output
    assert stored_refresh_token(credentials_file, host) == "wb_rt_old"


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_reusing_a_browser_login_persists_the_host(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(monkeypatch)
    browser_login.save_credentials(credentials_file, host, make_token_set())
    system_settings = wandb_setup.singleton().settings.read_system_settings()
    system_settings.set("base_url", "https://other-host.invalid", globally=True)
    system_settings.save()

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 0, result.output
    assert "Already logged in" in result.output
    saved_settings = wandb_setup.singleton().settings.read_system_settings()
    assert saved_settings.all().get("base_url") == host.url


@pytest.mark.usefixtures("local_settings")
def test_browser_flag_logs_in_again_when_the_stored_login_is_rejected(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(monkeypatch)
    browser_login.save_credentials(credentials_file, host, make_token_set("wb_rt_old"))
    verified: list[str | None] = []

    def reject_the_old_login(self: wbauth.AuthBrowserLogin) -> None:
        refresh_token = stored_refresh_token(credentials_file, self.host)
        verified.append(refresh_token)
        if refresh_token == "wb_rt_old":
            raise AuthenticationError("revoked")

    monkeypatch.setattr(wbauth.AuthBrowserLogin, "verify", reject_the_old_login)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 0, result.output
    assert verified == ["wb_rt_old", "wb_rt_new"]
    assert "Could not use the browser login stored for" in result.output
    assert revoked_tokens(oauth_server) == ["wb_rt_old"]
    assert stored_refresh_token(credentials_file, host) == "wb_rt_new"


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_browser_relogin_revokes_the_login_it_replaces(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(monkeypatch)
    browser_login.save_credentials(credentials_file, host, make_token_set("wb_rt_old"))

    result = runner.invoke(
        cli.cli,
        ["login", "--host", host.url, "--browser", "--relogin"],
    )

    assert result.exit_code == 0, result.output
    assert revoked_tokens(oauth_server) == ["wb_rt_old"]
    assert stored_refresh_token(credentials_file, host) == "wb_rt_new"


@pytest.mark.usefixtures("local_settings")
def test_browser_flag_fails_without_a_browser(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    api_key_logins: list[dict],
):
    monkeypatch.setattr(browser_login, "can_open_browser", lambda: False)
    mock_browser_login(monkeypatch)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 1, result.output
    assert oauth_server.received == []
    assert api_key_logins == []
    assert "needs a browser on this machine" in result.output


def test_browser_flag_rejects_a_key(runner, host: wbauth.HostUrl):
    result = runner.invoke(
        cli.cli,
        ["login", "--host", host.url, "--browser", "k" * 40],
    )

    assert result.exit_code == 1, result.output
    assert "Pass an API key or --browser, not both." in result.output


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_browser_login_persists_the_host(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    host: wbauth.HostUrl,
):
    mock_browser_login(monkeypatch)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 0, result.output
    saved_settings = wandb_setup.singleton().settings.read_system_settings()
    assert saved_settings.all().get("base_url") == host.url


@pytest.mark.usefixtures("local_settings", "skip_verify_login")
def test_browser_login_cloud_clears_a_saved_host(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    host: wbauth.HostUrl,
):
    monkeypatch.setattr(urls, "DEFAULT_BASE_URL", host.url)
    mock_browser_login(monkeypatch)
    system_settings = wandb_setup.singleton().settings.read_system_settings()
    system_settings.set("base_url", "https://self-hosted.invalid", globally=True)
    system_settings.save()

    result = runner.invoke(cli.cli, ["login", "--cloud", "--browser"])

    assert result.exit_code == 0, result.output
    saved_settings = wandb_setup.singleton().settings.read_system_settings()
    assert saved_settings.all().get("base_url") is None


@pytest.mark.usefixtures("local_settings")
def test_login_with_a_key_discards_a_browser_login(
    runner,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    api_key_logins: list[dict],
):
    browser_login.save_credentials(credentials_file, host, make_token_set())

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "k" * 40])

    assert result.exit_code == 0, result.output
    assert stored_refresh_token(credentials_file, host) is None
    assert revoked_tokens(oauth_server) == ["wb_rt_stored"]


@pytest.mark.usefixtures("local_settings")
def test_login_with_a_key_succeeds_when_revoking_fails(
    runner,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    api_key_logins: list[dict],
):
    browser_login.save_credentials(credentials_file, host, make_token_set())
    oauth_server.status = 500
    oauth_server.body = None

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "k" * 40])

    assert result.exit_code == 0, result.output
    assert "Could not revoke the previous browser login" in result.output
    assert stored_refresh_token(credentials_file, host) is None


@pytest.mark.usefixtures("local_settings")
def test_login_with_a_key_warns_when_the_browser_login_cannot_be_removed(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    api_key_logins: list[dict],
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


@pytest.mark.usefixtures("local_settings")
def test_login_with_a_key_leaves_the_credentials_file_alone_without_a_browser_login(
    runner,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    api_key_logins: list[dict],
):
    result = runner.invoke(cli.cli, ["login", "--host", host.url, "k" * 40])

    assert result.exit_code == 0, result.output
    assert not credentials_file.exists()
    assert not credentials_file.with_name(f"{credentials_file.name}.lock").exists()


@pytest.mark.usefixtures("local_settings")
def test_rejected_api_key_keeps_the_browser_login(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    browser_login.save_credentials(credentials_file, host, make_token_set())

    def reject_api_key(**kwargs: object) -> bool:
        raise AuthenticationError("rejected")

    monkeypatch.setattr("wandb.login", reject_api_key)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "k" * 40])

    assert result.exit_code == 1, result.output
    assert stored_refresh_token(credentials_file, host) == "wb_rt_stored"
    assert revoked_tokens(oauth_server) == []


@pytest.mark.usefixtures("local_settings")
def test_browser_relogin_keeps_the_previous_login_when_the_new_one_fails(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(
        monkeypatch,
        query={"error": "access_denied", "error_description": "You cancelled."},
    )
    browser_login.save_credentials(credentials_file, host, make_token_set("wb_rt_old"))

    result = runner.invoke(
        cli.cli,
        ["login", "--host", host.url, "--browser", "--relogin"],
    )

    assert result.exit_code == 1, result.output
    assert "You cancelled." in result.output
    assert stored_refresh_token(credentials_file, host) == "wb_rt_old"
    assert oauth_server.received == []


@pytest.mark.usefixtures("local_settings")
def test_browser_relogin_restores_the_previous_login_when_verify_fails(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(monkeypatch)
    browser_login.save_credentials(credentials_file, host, make_token_set("wb_rt_old"))
    monkeypatch.setattr(
        ServiceApi,
        "authenticate",
        MagicMock(side_effect=RuntimeError("rejected")),
    )

    result = runner.invoke(
        cli.cli,
        ["login", "--host", host.url, "--browser", "--relogin"],
    )

    assert result.exit_code == 1, result.output
    assert stored_refresh_token(credentials_file, host) == "wb_rt_old"
    assert revoked_tokens(oauth_server) == ["wb_rt_new"]


@pytest.mark.usefixtures("local_settings")
def test_browser_relogin_restores_the_previous_login_on_ctrl_c(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(monkeypatch)
    browser_login.save_credentials(credentials_file, host, make_token_set("wb_rt_old"))
    monkeypatch.setattr(
        ServiceApi,
        "authenticate",
        MagicMock(side_effect=KeyboardInterrupt),
    )

    result = runner.invoke(
        cli.cli,
        ["login", "--host", host.url, "--browser", "--relogin"],
    )

    assert result.exit_code == 1, result.output
    assert stored_refresh_token(credentials_file, host) == "wb_rt_old"
    assert revoked_tokens(oauth_server) == []


@pytest.mark.usefixtures("local_settings")
def test_failed_first_browser_login_stores_nothing(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(monkeypatch)
    monkeypatch.setattr(
        ServiceApi,
        "authenticate",
        MagicMock(side_effect=RuntimeError("rejected")),
    )

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 1, result.output
    assert stored_refresh_token(credentials_file, host) is None
    assert revoked_tokens(oauth_server) == ["wb_rt_new"]


@pytest.mark.usefixtures("local_settings")
def test_failed_browser_login_warns_when_revoking_fails(
    runner,
    monkeypatch: pytest.MonkeyPatch,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
):
    mock_browser_login(monkeypatch)
    monkeypatch.setattr(
        ServiceApi,
        "authenticate",
        MagicMock(side_effect=RuntimeError("rejected")),
    )

    def fail_revoke(**kwargs: object) -> None:
        raise AuthenticationError("server unavailable")

    monkeypatch.setattr(browser_login, "revoke", fail_revoke)

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--browser"])

    assert result.exit_code == 1, result.output
    assert "Could not revoke the new browser login" in result.output
    assert stored_refresh_token(credentials_file, host) is None


@pytest.mark.usefixtures("local_settings")
def test_login_with_no_key_keeps_a_browser_login(
    runner,
    oauth_server: FakeOAuthServer,
    host: wbauth.HostUrl,
    credentials_file: pathlib.Path,
    api_key_logins: list[dict],
):
    browser_login.save_credentials(credentials_file, host, make_token_set())

    result = runner.invoke(cli.cli, ["login", "--host", host.url, "--verify"])

    assert result.exit_code == 0, result.output
    assert stored_refresh_token(credentials_file, host) == "wb_rt_stored"
    assert revoked_tokens(oauth_server) == []
