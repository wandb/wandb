"""Tests for `wandb login` and `wandb logout`.

`wandb login` with no arguments runs the browser flow, so most of these fix
whether a browser is reachable and then assert which of the two login paths
the command took.
"""

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
    """Pin the browser decision so it does not depend on the test machine."""
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
    """Skip the round trip to the server that confirms the new credentials."""
    monkeypatch.setattr(wbauth.AuthBrowserLogin, "verify", lambda self: None)


@pytest.fixture
def fake_login(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stand in for the browser half of the login.

    Empty after a command means the browser flow was not used.
    """
    calls: dict = {}

    def fake(**kwargs: object) -> browser_login.TokenSet:
        calls.update(kwargs)
        return some_tokens("wb_rt_fresh")

    monkeypatch.setattr(browser_login, "login", fake)
    return calls


@pytest.fixture
def api_key_logins(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Record wandb.login() calls, reporting no credentials already configured.

    `prompt=False` is the command's probe for existing credentials, so
    answering it with False is what sends the command on to a fresh login.
    """
    calls: list[dict] = []

    def fake(**kwargs: object) -> bool:
        calls.append(kwargs)
        return kwargs.get("prompt") is not False

    monkeypatch.setattr("wandb.login", fake)
    return calls


@pytest.fixture
def already_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report that credentials for the host already resolve."""
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
    """Running this twice should not start a second login.

    Keeping the command idempotent is what lets it stay in scripts and CI,
    where the credentials come from the environment and no browser exists.
    """
    result = runner.invoke(cli.cli, ["login", "--host", HOST])

    assert result.exit_code == 0, result.output
    assert fake_login == {}


@pytest.mark.usefixtures("local_settings", "already_authenticated", "no_verify")
def test_relogin_starts_a_new_login_even_when_authenticated(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    revocations: list[str],
):
    result = runner.invoke(cli.cli, ["login", "--host", HOST, "--relogin"])

    assert result.exit_code == 0, result.output
    assert fake_login != {}


@pytest.mark.usefixtures("local_settings", "already_authenticated", "no_verify")
def test_relogin_revokes_the_login_it_replaces(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    revocations: list[str],
):
    """The superseded refresh token should stop working.

    Overwriting the file alone would leave it usable until its refresh family
    expired, so every --relogin would leak a live credential.
    """
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
    # The fallback has to actually prompt, which means relogin, or it would
    # re-read existing credentials instead of asking.
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
    """Asking for the browser explicitly should not be second-guessed.

    The environment check is a heuristic, and someone who names the method
    knows more about their setup than the heuristic does.
    """
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
def test_login_passes_the_organization_through(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
):
    result = runner.invoke(
        cli.cli,
        ["login", "--host", HOST, "--org", "my-org"],
    )

    assert result.exit_code == 0, result.output
    assert fake_login["organization"] == "my-org"


@pytest.mark.usefixtures("local_settings", "no_verify")
def test_login_leaves_the_organization_to_the_browser(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
):
    result = runner.invoke(cli.cli, ["login", "--host", HOST])

    assert result.exit_code == 0, result.output
    # None rather than "", so the consent page shows its picker instead of
    # looking for an organization with an empty name.
    assert fake_login["organization"] is None


@pytest.mark.usefixtures("local_settings", "no_verify")
def test_login_persists_the_host(
    runner,
    credentials_file: pathlib.Path,
    fake_login: dict,
    api_key_logins: list[dict],
):
    """`wandb login --host` should stick as the default host.

    Otherwise a later `wandb login --verify` (or anything else that defaults
    the host from settings) silently falls back to whatever host was
    previously configured, making the login appear to have no effect.
    """
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
    """`sso` parses as an API key now, which is a confusing way to fail."""
    result = runner.invoke(cli.cli, ["login", "sso", "--host", HOST])

    assert result.exit_code != 0
    assert "replaced by plain `wandb login`" in result.output


def test_login_rejects_a_key_with_browser_options(
    runner,
    credentials_file: pathlib.Path,
):
    result = runner.invoke(
        cli.cli,
        ["login", "--host", HOST, "--org", "my-org", "k" * 40],
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
    # A stored browser login outranks .netrc, so leaving it would make the
    # key the user just supplied look like it did not take.
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
    """A plain `wandb login` must not discard a stored browser login.

    Regression test: checking the session right after logging in was revoking
    the credentials it had just stored and falling back to a prompt, because
    the API key path cleared any browser login for the host before doing
    anything else.
    """
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
    # Both halves matter: clearing the file alone would leave the token
    # working for anyone who copied it.
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
    # The key outranked nothing while the browser login was stored, and is
    # about to start being used. Saying "logged out" and leaving the user
    # authenticated would be a lie.
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

    # The command reports the failure, but the credentials are off this
    # machine either way: keeping them until the server can be reached would
    # leave a usable token on the box the user asked to clean.
    assert result.exit_code != 0
    assert (
        browser_login.load_credentials(credentials_file, wbauth.HostUrl(HOST)) is None
    )
