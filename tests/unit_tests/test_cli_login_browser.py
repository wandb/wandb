"""`wandb login` and `wandb logout`."""

from __future__ import annotations

import datetime
import pathlib

import pytest
from wandb.cli import cli
from wandb.errors import AuthenticationError
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth
from wandb.sdk.lib.wbauth import browser_login

HOST = "https://test-host"


def some_tokens(refresh_token: str = "wb_rt_stored") -> browser_login.TokenSet:
    return browser_login.TokenSet(
        access_token="wb_at_stored",
        refresh_token=refresh_token,
        expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc),
    )


@pytest.fixture(autouse=True)
def browser_is_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the browser check so it does not depend on this machine."""
    monkeypatch.setattr(browser_login, "can_open_browser", lambda: True)


@pytest.fixture
def credentials_file(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> pathlib.Path:
    path = tmp_path / "credentials.json"
    monkeypatch.setenv("WANDB_CREDENTIALS_FILE", str(path))
    wandb_setup.singleton().settings.credentials_file = str(path)
    return path


@pytest.fixture
def no_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the server round trip that confirms the new credentials."""
    monkeypatch.setattr(wbauth.AuthBrowserLogin, "verify", lambda self: None)


@pytest.fixture
def fake_login(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stand in for the browser half of login. Empty means it was not used."""
    calls: dict = {}

    def fake(**kwargs: object) -> browser_login.TokenSet:
        calls.update(kwargs)
        return some_tokens("wb_rt_fresh")

    monkeypatch.setattr(browser_login, "login", fake)
    return calls


@pytest.fixture
def api_key_logins(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Record wandb.login() calls. prompt=False is answered as "not logged in"."""
    calls: list[dict] = []

    def fake(**kwargs: object) -> bool:
        calls.append(kwargs)
        return kwargs.get("prompt") is not False

    monkeypatch.setattr("wandb.login", fake)
    return calls


@pytest.fixture
def already_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wandb.login", lambda **kw: True)


@pytest.fixture
def revocations(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    revoked: list[str] = []
    monkeypatch.setattr(
        browser_login,
        "revoke",
        lambda *, host, refresh_token, **kw: revoked.append(refresh_token),
    )
    return revoked


@pytest.mark.usefixtures("local_settings", "no_verify")
def test_login_uses_the_browser_by_default(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
):
    result = runner.invoke(cli.cli, ["login", "--host", HOST])

    assert result.exit_code == 0, result.output
    stored = browser_login.load_credentials(credentials_file, wbauth.HostUrl(HOST))
    assert stored.refresh_token == "wb_rt_fresh"


@pytest.mark.usefixtures("local_settings", "already_authenticated")
def test_login_reuses_existing_credentials(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
):
    result = runner.invoke(cli.cli, ["login", "--host", HOST])

    assert result.exit_code == 0, result.output
    assert fake_login == {}


@pytest.mark.usefixtures("local_settings", "already_authenticated", "no_verify")
def test_relogin_revokes_the_login_it_replaces(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    revocations: list[str],
):
    browser_login.save_credentials(
        credentials_file, wbauth.HostUrl(HOST), some_tokens("wb_rt_old")
    )

    result = runner.invoke(cli.cli, ["login", "--host", HOST, "--relogin"])

    assert result.exit_code == 0, result.output
    assert revocations == ["wb_rt_old"]
    stored = browser_login.load_credentials(credentials_file, wbauth.HostUrl(HOST))
    assert stored.refresh_token == "wb_rt_fresh"


@pytest.mark.usefixtures("local_settings")
def test_login_falls_back_to_an_api_key_without_a_browser(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(browser_login, "can_open_browser", lambda: False)

    result = runner.invoke(cli.cli, ["login", "--host", HOST])

    assert result.exit_code == 0, result.output
    assert fake_login == {}
    assert api_key_logins[-1]["relogin"] is True
    assert "No usable browser" in result.output


@pytest.mark.usefixtures("local_settings", "no_verify")
def test_browser_flag_overrides_the_environment_checks(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(browser_login, "can_open_browser", lambda: False)

    result = runner.invoke(cli.cli, ["login", "--host", HOST, "--browser"])

    assert result.exit_code == 0, result.output
    assert fake_login != {}


@pytest.mark.usefixtures("local_settings")
def test_no_browser_asks_for_an_api_key(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
):
    result = runner.invoke(cli.cli, ["login", "--host", HOST, "--no-browser"])

    assert result.exit_code == 0, result.output
    assert fake_login == {}
    assert api_key_logins[-1]["relogin"] is True


@pytest.mark.usefixtures("local_settings", "no_verify")
def test_login_persists_the_host(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
):
    result = runner.invoke(cli.cli, ["login", "--host", HOST])

    assert result.exit_code == 0, result.output
    saved_settings = wandb_setup.singleton().settings.read_system_settings()
    assert saved_settings.all().get("base_url") == HOST


@pytest.mark.usefixtures("local_settings", "no_verify")
def test_login_cloud_clears_a_saved_host(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
):
    system_settings = wandb_setup.singleton().settings.read_system_settings()
    system_settings.set("base_url", HOST, globally=True)
    system_settings.save()

    result = runner.invoke(cli.cli, ["login", "--cloud"])

    assert result.exit_code == 0, result.output
    saved_settings = wandb_setup.singleton().settings.read_system_settings()
    assert saved_settings.all().get("base_url") is None


def test_login_rejects_host_with_cloud(runner, credentials_file: pathlib.Path):
    result = runner.invoke(cli.cli, ["login", "--cloud", "--host", HOST])

    assert result.exit_code != 0
    assert "Cannot use --host and --cloud together." in result.output


def test_login_sso_points_at_the_new_spelling(
    runner,
    credentials_file: pathlib.Path,
):
    result = runner.invoke(cli.cli, ["login", "sso", "--host", HOST])

    assert result.exit_code != 0
    assert "replaced by plain `wandb login`" in result.output


def test_login_rejects_a_key_with_browser_options(
    runner,
    credentials_file: pathlib.Path,
):
    result = runner.invoke(
        cli.cli,
        ["login", "--host", HOST, "--browser", "k" * 40],
    )

    assert result.exit_code != 0
    assert "cannot be combined" in result.output


@pytest.mark.usefixtures("local_settings")
def test_login_with_a_key_discards_a_browser_login(
    runner,
    credentials_file: pathlib.Path,
    revocations: list[str],
    api_key_logins: list[dict],
):
    browser_login.save_credentials(
        credentials_file, wbauth.HostUrl(HOST), some_tokens()
    )

    result = runner.invoke(cli.cli, ["login", "--host", HOST, "k" * 40])

    assert result.exit_code == 0, result.output
    assert (
        browser_login.load_credentials(credentials_file, wbauth.HostUrl(HOST)) is None
    )
    assert revocations == ["wb_rt_stored"]


@pytest.mark.usefixtures("local_settings", "already_authenticated")
def test_login_with_no_key_keeps_a_browser_login(
    runner,
    credentials_file: pathlib.Path,
    revocations: list[str],
    fake_login: dict,
):
    browser_login.save_credentials(
        credentials_file, wbauth.HostUrl(HOST), some_tokens()
    )

    result = runner.invoke(cli.cli, ["login", "--host", HOST, "--verify"])

    assert result.exit_code == 0, result.output
    assert (
        browser_login.load_credentials(credentials_file, wbauth.HostUrl(HOST))
        is not None
    )
    assert revocations == []


def test_logout_revokes_and_clears(
    runner,
    credentials_file: pathlib.Path,
    revocations: list[str],
):
    browser_login.save_credentials(
        credentials_file, wbauth.HostUrl(HOST), some_tokens()
    )

    result = runner.invoke(cli.cli, ["logout", "--host", HOST])

    assert result.exit_code == 0, result.output
    assert revocations == ["wb_rt_stored"]
    assert (
        browser_login.load_credentials(credentials_file, wbauth.HostUrl(HOST)) is None
    )


def test_logout_when_not_logged_in(
    runner,
    credentials_file: pathlib.Path,
    revocations: list[str],
):
    result = runner.invoke(cli.cli, ["logout", "--host", HOST])

    assert result.exit_code == 0, result.output
    assert "Not logged in" in result.output
    assert revocations == []


def test_logout_warns_about_a_surviving_api_key(
    runner,
    credentials_file: pathlib.Path,
    revocations: list[str],
    monkeypatch: pytest.MonkeyPatch,
):
    browser_login.save_credentials(
        credentials_file, wbauth.HostUrl(HOST), some_tokens()
    )
    monkeypatch.setattr(wbauth, "read_netrc_auth", lambda *, host: "k" * 40)

    result = runner.invoke(cli.cli, ["logout", "--host", HOST])

    assert result.exit_code == 0, result.output
    assert ".netrc" in result.output


def test_logout_clears_locally_even_if_revoking_fails(
    runner,
    credentials_file: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    browser_login.save_credentials(
        credentials_file, wbauth.HostUrl(HOST), some_tokens()
    )

    def fail(**kwargs: object) -> None:
        raise AuthenticationError("server unreachable")

    monkeypatch.setattr(browser_login, "revoke", fail)

    result = runner.invoke(cli.cli, ["logout", "--host", HOST])

    assert result.exit_code != 0
    assert (
        browser_login.load_credentials(credentials_file, wbauth.HostUrl(HOST)) is None
    )
