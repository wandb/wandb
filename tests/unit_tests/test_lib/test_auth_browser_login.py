"""Tests for the browser login flow and the credentials file it writes."""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
import threading
import urllib.parse
import urllib.request

import pytest
import requests
from wandb.errors import AuthenticationError
from wandb.sdk.lib import ipython
from wandb.sdk.lib.wbauth import browser_login
from wandb.sdk.lib.wbauth.host_url import HostUrl

HOST = HostUrl("https://test-host")


class FakeResponse:
    """Stands in for a requests.Response from the token endpoint."""

    def __init__(self, *, status_code: int = 200, body: object = None) -> None:
        self.status_code = status_code
        self._body = body

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> object:
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


@pytest.fixture
def token_endpoint(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture token and revocation requests, answering them successfully."""
    requests_made: list[dict] = []

    def fake_post(url: str, *, data: dict, **kwargs: object) -> FakeResponse:
        requests_made.append({"url": url, "data": data, **kwargs})
        return FakeResponse(
            body={
                "access_token": "wb_at_new",
                "refresh_token": "wb_rt_new",
                "expires_in": 3600,
                "token_type": "bearer",
            }
        )

    monkeypatch.setattr(browser_login.requests, "post", fake_post)
    return requests_made


def complete_login_in_browser(
    monkeypatch: pytest.MonkeyPatch,
    *,
    query: dict[str, str] | None = None,
    state: str | None = None,
) -> dict[str, str]:
    """Answer the authorization request the way the server would.

    Replaces the browser with a thread that calls the loopback redirect, since
    the login blocks waiting for it and cannot perform the call itself.

    Returns the parameters the CLI put in the authorization URL.
    """
    captured: dict[str, str] = {}

    def fake_open(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        captured.update(params)
        captured["path"] = parsed.path

        callback = dict(query or {"code": "auth-code"})
        callback.setdefault("state", state or params["state"])
        redirect = f"{params['redirect_uri']}?{urllib.parse.urlencode(callback)}"

        def hit_loopback() -> None:
            # The loopback response redirects to a host that does not exist
            # in this test. All that matters here is that the loopback server
            # received the callback, so ignore whatever happens next.
            try:
                urllib.request.urlopen(redirect).read()
            except (urllib.error.URLError, ConnectionError):
                pass

        threading.Thread(target=hit_loopback, daemon=True).start()
        return True

    monkeypatch.setattr(browser_login, "_open_browser", fake_open)
    return captured


def test_login_exchanges_the_code_for_tokens(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    complete_login_in_browser(monkeypatch)

    tokens = browser_login.login(host=HOST, timeout=10)

    assert tokens.access_token == "wb_at_new"
    assert tokens.refresh_token == "wb_rt_new"

    assert len(token_endpoint) == 1
    sent = token_endpoint[0]
    assert sent["url"] == "https://test-host/oidc/token"
    assert sent["data"]["grant_type"] == "authorization_code"
    assert sent["data"]["code"] == "auth-code"
    assert sent["data"]["client_id"] == browser_login.CLI_CLIENT_ID


def test_loopback_hands_the_tab_off_to_the_success_page(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    """The last thing the browser sees should be a W&B page, not local HTML."""
    redirect_target: dict[str, str] = {}
    # login() returns as soon as it has the code, which is before the stand-in
    # browser has finished reading the response. Without waiting for the thread
    # the assertion races it.
    responded = threading.Event()

    def fake_open(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        callback_url = (
            f"{params['redirect_uri']}?code=auth-code&state={params['state']}"
        )

        def hit_loopback() -> None:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    redirect_target["location"] = newurl
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            try:
                opener.open(callback_url).read()
            except urllib.error.HTTPError:
                pass
            finally:
                responded.set()

        threading.Thread(target=hit_loopback, daemon=True).start()
        return True

    monkeypatch.setattr(browser_login, "_open_browser", fake_open)

    browser_login.login(host=HOST, timeout=10)

    assert responded.wait(timeout=10), "the loopback request never completed"
    assert redirect_target["location"] == f"{HOST.app_url}/cli-login-success"


def test_loopback_hands_a_denied_login_off_to_the_cancelled_page(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    redirect_target: dict[str, str] = {}
    responded = threading.Event()

    def fake_open(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        callback_url = (
            f"{params['redirect_uri']}?error=access_denied"
            "&error_description=You+cancelled+the+login."
        )

        def hit_loopback() -> None:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    redirect_target["location"] = newurl
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            try:
                opener.open(callback_url).read()
            except urllib.error.HTTPError:
                pass
            finally:
                responded.set()

        threading.Thread(target=hit_loopback, daemon=True).start()
        return True

    monkeypatch.setattr(browser_login, "_open_browser", fake_open)

    with pytest.raises(AuthenticationError, match="You cancelled the login."):
        browser_login.login(host=HOST, timeout=10)

    assert responded.wait(timeout=10), "the loopback request never completed"
    assert redirect_target["location"] == f"{HOST.app_url}/cli-login-cancelled"


def test_login_opens_the_consent_page_with_a_pkce_challenge(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    captured = complete_login_in_browser(monkeypatch)

    browser_login.login(host=HOST, organization="my-org", timeout=10)

    assert captured["path"] == "/cli-login"
    assert captured["response_type"] == "code"
    assert captured["code_challenge_method"] == "S256"
    assert captured["organization"] == "my-org"
    assert "scope" not in captured
    # The challenge is sent, the verifier is not: that is the whole point, so
    # that intercepting this URL does not let someone else redeem the code.
    assert captured["code_challenge"]
    assert "code_verifier" not in captured
    assert token_endpoint[0]["data"]["code_verifier"]


def test_login_redirects_to_loopback_only(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    captured = complete_login_in_browser(monkeypatch)

    browser_login.login(host=HOST, timeout=10)

    # The authorization code arrives on this address, so it must not be
    # reachable from outside this machine.
    redirect = urllib.parse.urlparse(captured["redirect_uri"])
    assert redirect.hostname == "127.0.0.1"
    assert redirect.path == browser_login.CALLBACK_PATH


def test_login_omits_organization_when_not_given(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    captured = complete_login_in_browser(monkeypatch)

    browser_login.login(host=HOST, timeout=10)

    # Absent rather than empty, so the consent page knows to ask instead of
    # looking for an organization with no name.
    assert "organization" not in captured


def test_login_rejects_a_mismatched_state(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    complete_login_in_browser(monkeypatch, state="not-the-state-we-sent")

    # A response that does not carry back our state did not come from the
    # login we started, so its code is not ours to redeem.
    with pytest.raises(AuthenticationError, match="did not match the request"):
        browser_login.login(host=HOST, timeout=10)

    assert token_endpoint == []


def test_login_reports_a_denied_request(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    complete_login_in_browser(
        monkeypatch,
        query={
            "error": "access_denied",
            "error_description": "You cancelled the login.",
        },
    )

    with pytest.raises(AuthenticationError, match="You cancelled the login."):
        browser_login.login(host=HOST, timeout=10)


def test_login_rejects_a_response_without_a_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
):
    complete_login_in_browser(monkeypatch)
    monkeypatch.setattr(
        browser_login.requests,
        "post",
        lambda *a, **k: FakeResponse(body={"access_token": "wb_at_new"}),
    )

    # Without a refresh token the login would last only as long as the first
    # access token, and would fail later rather than here.
    with pytest.raises(AuthenticationError, match="incomplete token response"):
        browser_login.login(host=HOST, timeout=10)


def test_login_surfaces_the_servers_error(
    monkeypatch: pytest.MonkeyPatch,
):
    complete_login_in_browser(monkeypatch)
    monkeypatch.setattr(
        browser_login.requests,
        "post",
        lambda *a, **k: FakeResponse(
            status_code=400,
            body={
                "error": "invalid_grant",
                "error_description": "The code expired.",
            },
        ),
    )

    with pytest.raises(AuthenticationError, match="The code expired."):
        browser_login.login(host=HOST, timeout=10)


def test_login_honors_disabled_tls_verification(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    complete_login_in_browser(monkeypatch)

    # This is the only HTTP the Python side makes; everything else goes
    # through wandb-core, which has its own setting. Ignoring it here meant
    # the exchange failed against a self-signed development server even
    # though every other request to it worked.
    browser_login.login(host=HOST, timeout=10, verify=False)

    assert token_endpoint[0]["verify"] is False


def test_login_verifies_tls_by_default(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint: list[dict],
):
    complete_login_in_browser(monkeypatch)

    browser_login.login(host=HOST, timeout=10)

    assert token_endpoint[0]["verify"] is True


def test_login_times_out_waiting_for_the_browser(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(browser_login, "_open_browser", lambda url: True)

    with pytest.raises(TimeoutError):
        browser_login.login(host=HOST, timeout=0.1)


def some_tokens(refresh_token: str = "wb_rt_stored") -> browser_login.TokenSet:
    return browser_login.TokenSet(
        access_token="wb_at_stored",
        refresh_token=refresh_token,
        expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc),
    )


def test_credentials_round_trip(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"

    browser_login.save_credentials(path, HOST, some_tokens())
    loaded = browser_login.load_credentials(path, HOST)

    assert loaded == some_tokens()


def test_credentials_are_written_where_core_can_read_them(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"

    browser_login.save_credentials(path, HOST, some_tokens())

    # The shape and the timestamp format are a contract with wandb-core, which
    # reads this file and refreshes the token in it.
    contents = json.loads(path.read_text())
    assert contents == {
        "credentials": {
            "https://test-host": {
                "expires_at": "2030-01-01 00:00:00",
                "access_token": "wb_at_stored",
                "refresh_token": "wb_rt_stored",
            }
        }
    }


def test_credentials_are_not_world_readable(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"

    browser_login.save_credentials(path, HOST, some_tokens())

    assert path.stat().st_mode & 0o077 == 0


def test_saving_leaves_other_hosts_alone(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    other = HostUrl("https://other-host")

    browser_login.save_credentials(path, other, some_tokens("wb_rt_other"))
    browser_login.save_credentials(path, HOST, some_tokens())

    # One file holds every deployment's login, so writing one must not log the
    # user out of the rest.
    assert browser_login.load_credentials(path, other).refresh_token == "wb_rt_other"
    assert browser_login.load_credentials(path, HOST).refresh_token == "wb_rt_stored"


def test_loading_a_host_that_is_not_stored(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    browser_login.save_credentials(path, HostUrl("https://other-host"), some_tokens())

    assert browser_login.load_credentials(path, HOST) is None


def test_loading_a_missing_file(tmp_path: pathlib.Path):
    # Never having logged in is the ordinary case, not an error.
    assert browser_login.load_credentials(tmp_path / "nope.json", HOST) is None


def test_loading_a_corrupt_file(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    path.write_text("{not json")

    assert browser_login.load_credentials(path, HOST) is None


def test_loading_ignores_an_identity_token_entry(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    # What a federated identity login leaves: an access token cache with
    # nothing to refresh from. It is not a browser login.
    path.write_text(
        json.dumps(
            {
                "credentials": {
                    "https://test-host": {
                        "expires_at": "2030-01-01 00:00:00",
                        "access_token": "wb_at_federated",
                    }
                }
            }
        )
    )

    assert browser_login.load_credentials(path, HOST) is None


def test_clearing_removes_and_returns_the_login(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    browser_login.save_credentials(path, HOST, some_tokens())

    cleared = browser_login.clear_credentials(path, HOST)

    # Returned so the caller can revoke it: removing the file copy alone
    # leaves the token working for anyone who took one.
    assert cleared.refresh_token == "wb_rt_stored"
    assert browser_login.load_credentials(path, HOST) is None


def test_clearing_when_not_logged_in(tmp_path: pathlib.Path):
    assert browser_login.clear_credentials(tmp_path / "nope.json", HOST) is None


def test_can_open_browser_rejects_a_remote_shell(monkeypatch: pytest.MonkeyPatch):
    """A browser over SSH opens on the wrong machine.

    The loopback listener is here and the browser is there, so the redirect
    lands nowhere and the login hangs until it times out instead of failing.
    """
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 22")

    assert browser_login.can_open_browser() is False


def test_can_open_browser_rejects_a_notebook(monkeypatch: pytest.MonkeyPatch):
    """Same problem as SSH whenever the kernel is not the user's machine."""
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(ipython, "in_jupyter", lambda: True)

    assert browser_login.can_open_browser() is False


def test_can_open_browser_rejects_a_non_interactive_process(
    monkeypatch: pytest.MonkeyPatch,
):
    """Nobody is watching, so nothing should be waiting on a browser."""
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(ipython, "in_jupyter", lambda: False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)

    assert browser_login.can_open_browser() is False


def test_revoke_sends_the_refresh_token(monkeypatch: pytest.MonkeyPatch):
    sent: dict = {}

    def fake_post(url: str, *, data: dict, **kwargs: object) -> FakeResponse:
        sent.update({"url": url, "data": data, **kwargs})
        return FakeResponse(body={})

    monkeypatch.setattr(browser_login.requests, "post", fake_post)

    browser_login.revoke(host=HOST, refresh_token="wb_rt_stored")

    assert sent["url"] == "https://test-host/oidc/revoke"
    # Revoking the refresh token is what ends the login. Revoking the access
    # token would leave the refresh token able to mint another.
    assert sent["data"]["token"] == "wb_rt_stored"
    assert sent["data"]["token_type_hint"] == "refresh_token"


def test_revoke_reports_a_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        browser_login.requests,
        "post",
        lambda *a, **k: FakeResponse(status_code=500, body=None),
    )

    with pytest.raises(AuthenticationError, match="Failed to log out"):
        browser_login.revoke(host=HOST, refresh_token="wb_rt_stored")
