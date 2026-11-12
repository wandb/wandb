"""Browser login flow and the credentials file it writes."""

from __future__ import annotations

import contextlib
import datetime
import http.server
import json
import os
import pathlib
import socket
import ssl
import sys
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable, Iterator

import pytest
from wandb import util
from wandb.errors import AuthenticationError
from wandb.sdk.lib import ipython
from wandb.sdk.lib.wbauth import browser_login
from wandb.sdk.lib.wbauth.host_url import HostUrl

HOST = HostUrl("https://test-host")

TOKEN_RESPONSE = {
    "access_token": "wb_at_new",
    "refresh_token": "wb_rt_new",
    "expires_in": 3600,
    "token_type": "bearer",
}


class FakeOAuthServer:
    """The W&B server's OAuth endpoints, served on a loopback port.

    Every request is recorded in `received` as its path plus its form fields.
    Each one is answered with `status` and `body`; a `body` of None sends an
    empty response. Set `stall` to hold every response until the server stops.
    """

    def __init__(self, host: HostUrl) -> None:
        self.host = host
        self.received: list[dict[str, str]] = []
        self.status = 200
        self.body: object = TOKEN_RESPONSE
        self.stall = False
        self.stopped = threading.Event()


@contextlib.contextmanager
def serve_oauth(tls: ssl.SSLContext | None = None) -> Iterator[FakeOAuthServer]:
    fake: FakeOAuthServer

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            form = urllib.parse.parse_qsl(self.rfile.read(length).decode())
            fake.received.append({"path": self.path, **dict(form)})
            if fake.stall:
                fake.stopped.wait()

            body = b"" if fake.body is None else json.dumps(fake.body).encode()
            self.send_response(fake.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    scheme = "http"
    if tls is not None:
        httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    url = f"{scheme}://127.0.0.1:{httpd.server_address[1]}"
    fake = FakeOAuthServer(HostUrl(url, app_url="https://test-app"))

    thread = threading.Thread(
        target=httpd.serve_forever,
        kwargs={"poll_interval": 0.01},
        daemon=True,
    )
    thread.start()
    try:
        yield fake
    finally:
        fake.stopped.set()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def oauth_server() -> Iterator[FakeOAuthServer]:
    with serve_oauth() as server:
        yield server


@pytest.fixture
def tls_context(assets_path: Callable[[str], pathlib.Path]) -> ssl.SSLContext:
    certs = assets_path("ssl_certs")
    [cert] = certs.glob("*.0")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert), keyfile=str(certs / "localhost.key"))
    return context


def mock_browser_login(
    monkeypatch: pytest.MonkeyPatch,
    *,
    query: dict[str, str] | None = None,
    redirect_target: dict[str, str] | None = None,
    responded: threading.Event | None = None,
    before_redirect: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Replace the browser with one that approves the login immediately.

    Instead of opening the consent page, sends the redirect the authorization
    server would, with `query` (an authorization code by default) and the
    request's state, to the CLI's loopback server.

    Returns the query the CLI put on the consent page URL. Pass
    redirect_target to record where the loopback response sends the browser,
    and before_redirect to act on the redirect URI first.
    """
    captured: dict[str, str] = {}

    def fake_open(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        captured.update(params)
        captured["path"] = parsed.path

        callback = dict(query or {"code": "auth-code"})
        callback.setdefault("state", params["state"])
        redirect = f"{params['redirect_uri']}?{urllib.parse.urlencode(callback)}"

        def hit_loopback() -> None:
            try:
                if before_redirect is not None:
                    before_redirect(params["redirect_uri"])
                if redirect_target is None:
                    urllib.request.urlopen(redirect).read()
                else:
                    _open_without_following(redirect, redirect_target)
            except (urllib.error.URLError, ConnectionError):
                pass
            finally:
                if responded is not None:
                    responded.set()

        threading.Thread(target=hit_loopback, daemon=True).start()
        return True

    monkeypatch.setattr(browser_login, "_open_browser", fake_open)
    return captured


def _open_without_following(url: str, redirect_target: dict[str, str]) -> None:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            redirect_target["location"] = newurl
            return None

    try:
        urllib.request.build_opener(NoRedirect).open(url).read()
    except urllib.error.HTTPError:
        pass


def test_login_exchanges_the_code_for_tokens(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
):
    mock_browser_login(monkeypatch)

    tokens = browser_login.login(host=oauth_server.host, timeout=10)

    assert tokens.access_token == "wb_at_new"
    assert tokens.refresh_token == "wb_rt_new"

    [sent] = oauth_server.received
    assert sent["path"] == "/oidc/token"
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "auth-code"
    assert sent["client_id"] == browser_login.CLI_CLIENT_ID


def test_loopback_hands_the_tab_off_to_the_success_page(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
):
    redirect_target: dict[str, str] = {}
    responded = threading.Event()
    mock_browser_login(
        monkeypatch, redirect_target=redirect_target, responded=responded
    )

    browser_login.login(host=oauth_server.host, timeout=10)

    assert responded.wait(timeout=10)
    assert redirect_target["location"] == "https://test-app/cli-login-success"


@pytest.mark.parametrize(
    "query, message",
    [
        (
            {"error": "access_denied", "error_description": "You cancelled."},
            "You cancelled.",
        ),
        ({"error": "server_error", "error_description": "Oops."}, "Oops."),
        ({"error": "invalid_scope"}, "invalid_scope"),
        ({"foo": "bar"}, "did not include an authorization code"),
    ],
)
def test_loopback_hands_a_failed_login_off_to_the_cancelled_page(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    query: dict[str, str],
    message: str,
):
    redirect_target: dict[str, str] = {}
    responded = threading.Event()
    mock_browser_login(
        monkeypatch,
        query=query,
        redirect_target=redirect_target,
        responded=responded,
    )

    with pytest.raises(AuthenticationError, match=message):
        browser_login.login(host=oauth_server.host, timeout=10)

    assert responded.wait(timeout=10)
    assert redirect_target["location"] == "https://test-app/cli-login-cancelled"
    assert oauth_server.received == []


def test_loopback_hands_a_failed_exchange_off_to_the_cancelled_page(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
):
    redirect_target: dict[str, str] = {}
    responded = threading.Event()
    mock_browser_login(
        monkeypatch, redirect_target=redirect_target, responded=responded
    )
    oauth_server.status = 400
    oauth_server.body = {"error": "invalid_grant", "error_description": "Code expired."}

    with pytest.raises(AuthenticationError, match="Code expired."):
        browser_login.login(host=oauth_server.host, timeout=10)

    assert responded.wait(timeout=10)
    assert redirect_target["location"] == "https://test-app/cli-login-cancelled"


def _unused_exchange(params: dict[str, list[str]]) -> browser_login.TokenSet:
    raise AssertionError("no login ran")


@pytest.mark.parametrize(
    ("app_url", "consent", "root"),
    [
        # Forge serves the app under a path, and the login pages at the root.
        (
            "https://forge.coreweave.com/wandb",
            "https://forge.coreweave.com/cli-login",
            "https://forge.coreweave.com",
        ),
        ("https://test-app", "https://test-app/cli-login", "https://test-app"),
    ],
)
def test_login_pages_are_served_from_the_host_root(
    app_url: str, consent: str, root: str
):
    host = HostUrl("https://test-host", app_url=app_url)

    authorize_url = browser_login._authorize_url(
        host, redirect_uri="http://127.0.0.1/callback", state="s", challenge="c"
    )
    with browser_login._CallbackServer(host, "s", _unused_exchange) as server:
        assert server.success_url == f"{root}/cli-login-success"
        assert server.cancelled_url == f"{root}/cli-login-cancelled"
    assert authorize_url.startswith(f"{consent}?")


def test_login_opens_the_consent_page_with_a_pkce_challenge(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
):
    captured = mock_browser_login(monkeypatch)

    browser_login.login(host=oauth_server.host, timeout=10)

    assert captured["path"] == "/cli-login"
    assert urllib.parse.urlparse(captured["redirect_uri"]).hostname == "127.0.0.1"
    assert captured["response_type"] == "code"
    assert captured["code_challenge_method"] == "S256"
    assert captured["code_challenge"]
    assert "code_verifier" not in captured
    assert oauth_server.received[0]["code_verifier"]


def test_login_ignores_a_callback_with_the_wrong_state(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
):
    def send_stray_callbacks(redirect_uri: str) -> None:
        for state in ("not-the-state-we-sent", "\u00e9", ""):
            query = urllib.parse.urlencode({"code": "stray-code", "state": state})
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"{redirect_uri}?{query}")
            assert error.value.code == 400

    mock_browser_login(monkeypatch, before_redirect=send_stray_callbacks)

    browser_login.login(host=oauth_server.host, timeout=10)

    assert [request["code"] for request in oauth_server.received] == ["auth-code"]


def test_login_is_not_stalled_by_an_idle_connection(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
):
    monkeypatch.setattr(browser_login._CallbackHandler, "timeout", 0.1)
    idle_connections: list[socket.socket] = []

    def connect_and_stay_silent(redirect_uri: str) -> None:
        port = urllib.parse.urlparse(redirect_uri).port
        idle_connections.append(socket.create_connection(("127.0.0.1", port)))

    mock_browser_login(monkeypatch, before_redirect=connect_and_stay_silent)

    try:
        tokens = browser_login.login(host=oauth_server.host, timeout=10)
    finally:
        for connection in idle_connections:
            connection.close()

    assert tokens.refresh_token == "wb_rt_new"


def test_login_timeout_bounds_an_idle_connection(monkeypatch: pytest.MonkeyPatch):
    idle_connections: list[socket.socket] = []

    def connect_and_stay_silent(url: str) -> bool:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        port = urllib.parse.urlparse(query["redirect_uri"]).port
        idle_connections.append(socket.create_connection(("127.0.0.1", port)))
        return True

    monkeypatch.setattr(browser_login, "_open_browser", connect_and_stay_silent)

    start = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            browser_login.login(host=HOST, timeout=0.3)
    finally:
        for connection in idle_connections:
            connection.close()

    assert time.monotonic() - start < 2


def test_login_timeout_bounds_the_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
):
    mock_browser_login(monkeypatch)
    oauth_server.stall = True

    start = time.monotonic()
    with pytest.raises(AuthenticationError, match="Could not reach"):
        browser_login.login(host=oauth_server.host, timeout=0.3)

    assert time.monotonic() - start < 5


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"access_token": "wb_at_new"}, id="no-refresh-token"),
        pytest.param({"refresh_token": "wb_rt_new"}, id="no-access-token"),
        pytest.param(
            {"access_token": "", "refresh_token": "wb_rt_new"},
            id="empty-access-token",
        ),
        pytest.param(
            {"access_token": ["wb_at_new"], "refresh_token": "wb_rt_new"},
            id="list-access-token",
        ),
        pytest.param(
            {"access_token": "wb_at_new", "refresh_token": 123},
            id="int-refresh-token",
        ),
    ],
)
def test_login_rejects_an_incomplete_token_response(
    monkeypatch: pytest.MonkeyPatch,
    oauth_server: FakeOAuthServer,
    body: dict[str, object],
):
    mock_browser_login(monkeypatch)
    oauth_server.body = body

    with pytest.raises(AuthenticationError, match="incomplete token response"):
        browser_login.login(host=oauth_server.host, timeout=10)


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_login_honors_disabled_tls_verification(
    monkeypatch: pytest.MonkeyPatch,
    tls_context: ssl.SSLContext,
):
    mock_browser_login(monkeypatch)

    with serve_oauth(tls=tls_context) as server:
        tokens = browser_login.login(host=server.host, timeout=10, verify=False)

    assert tokens.refresh_token == "wb_rt_new"


def test_login_verifies_tls_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tls_context: ssl.SSLContext,
):
    mock_browser_login(monkeypatch)

    with serve_oauth(tls=tls_context) as server:
        with pytest.raises(AuthenticationError, match="Could not reach"):
            browser_login.login(host=server.host, timeout=10)

        assert server.received == []


def test_login_times_out_waiting_for_the_browser(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(browser_login, "_open_browser", lambda url: True)

    with pytest.raises(TimeoutError):
        browser_login.login(host=HOST, timeout=0.1)


def make_token_set(refresh_token: str = "wb_rt_stored") -> browser_login.TokenSet:
    return browser_login.TokenSet(
        access_token="wb_at_stored",
        refresh_token=refresh_token,
        expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc),
    )


def test_credentials_round_trip(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"

    browser_login.save_credentials(path, HOST, make_token_set())
    loaded = browser_login.load_credentials(path, HOST)

    assert loaded == make_token_set()


def test_credentials_are_written_where_core_can_read_them(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"

    browser_login.save_credentials(path, HOST, make_token_set())

    contents = json.loads(path.read_text())
    assert contents == {
        "credentials": {},
        "user_credentials": {
            "https://test-host": {
                "expires_at": "2030-01-01 00:00:00",
                "access_token": "wb_at_stored",
                "refresh_token": "wb_rt_stored",
            }
        },
    }


@pytest.mark.parametrize("contents", ["{not json", "[]"])
def test_saving_and_clearing_do_not_overwrite_a_corrupt_file(
    tmp_path: pathlib.Path, contents: str
):
    path = tmp_path / "credentials.json"
    path.write_text(contents)

    with pytest.raises(AuthenticationError):
        browser_login.save_credentials(path, HOST, make_token_set())
    with pytest.raises(AuthenticationError):
        browser_login.clear_credentials(path, HOST)

    assert path.read_text() == contents


def test_saving_leaves_an_identity_token_exchange_alone(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    workload = {
        "expires_at": "2030-01-01 00:00:00",
        "access_token": "wb_at_federated",
        "refresh_token": "wb_rt_federated",
    }
    path.write_text(json.dumps({"credentials": {"https://test-host": workload}}))

    browser_login.save_credentials(path, HOST, make_token_set())
    browser_login.clear_credentials(path, HOST)

    contents = json.loads(path.read_text())
    assert contents["credentials"] == {"https://test-host": workload}
    assert contents["user_credentials"] == {}


def test_save_waits_for_the_core_credentials_lock(tmp_path: pathlib.Path):
    if sys.platform == "win32":
        pytest.skip("this test takes the lock with flock")

    import fcntl

    path = tmp_path / "credentials.json"
    fd = os.open(path.with_name(f"{path.name}.lock"), os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    finished = threading.Event()

    def save() -> None:
        browser_login.save_credentials(path, HOST, make_token_set())
        finished.set()

    thread = threading.Thread(target=save)
    thread.start()
    try:
        assert not finished.wait(0.2)
        fcntl.flock(fd, fcntl.LOCK_UN)
        assert finished.wait(2)
    finally:
        os.close(fd)
        thread.join(timeout=2)

    assert browser_login.load_credentials(path, HOST).refresh_token == "wb_rt_stored"


def test_saving_reports_a_file_that_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(pathlib.Path, "replace", deny)

    with pytest.raises(AuthenticationError, match="Could not write"):
        browser_login.save_credentials(
            tmp_path / "credentials.json", HOST, make_token_set()
        )

    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".credentials-")]


def test_credentials_are_not_world_readable(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"

    browser_login.save_credentials(path, HOST, make_token_set())

    assert path.stat().st_mode & 0o077 == 0


def test_saving_leaves_other_hosts_alone(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    other = HostUrl("https://other-host")

    browser_login.save_credentials(path, other, make_token_set("wb_rt_other"))
    browser_login.save_credentials(path, HOST, make_token_set())

    assert browser_login.load_credentials(path, other).refresh_token == "wb_rt_other"
    assert browser_login.load_credentials(path, HOST).refresh_token == "wb_rt_stored"


def test_loading_a_host_that_is_not_stored(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    browser_login.save_credentials(
        path, HostUrl("https://other-host"), make_token_set()
    )

    assert browser_login.load_credentials(path, HOST) is None


def test_loading_a_missing_file(tmp_path: pathlib.Path):
    assert browser_login.load_credentials(tmp_path / "nope.json", HOST) is None


def test_loading_a_corrupt_file(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    path.write_text("{not json")

    assert browser_login.load_credentials(path, HOST) is None


def write_user_credentials(path: pathlib.Path, entry: dict[str, object]) -> None:
    path.write_text(json.dumps({"user_credentials": {HOST.url: entry}}))


@pytest.mark.parametrize("refresh_token", [None, "", 123, ["wb_rt_stored"]])
def test_loading_ignores_an_unusable_refresh_token(
    tmp_path: pathlib.Path, refresh_token: object
):
    path = tmp_path / "credentials.json"
    write_user_credentials(
        path,
        {
            "expires_at": "2030-01-01 00:00:00",
            "access_token": "wb_at_stored",
            "refresh_token": refresh_token,
        },
    )

    assert browser_login.load_credentials(path, HOST) is None


def test_loading_drops_an_unusable_access_token(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    write_user_credentials(
        path,
        {
            "expires_at": "2030-01-01 00:00:00",
            "access_token": ["wb_at_stored"],
            "refresh_token": "wb_rt_stored",
        },
    )

    loaded = browser_login.load_credentials(path, HOST)

    assert loaded is not None
    assert loaded.access_token == ""
    assert loaded.refresh_token == "wb_rt_stored"


def test_loading_ignores_an_identity_token_entry(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "credentials": {
                    "https://test-host": {
                        "expires_at": "2030-01-01 00:00:00",
                        "access_token": "wb_at_federated",
                        "refresh_token": "wb_rt_federated",
                    }
                }
            }
        )
    )

    assert browser_login.load_credentials(path, HOST) is None


def test_clearing_removes_and_returns_the_login(tmp_path: pathlib.Path):
    path = tmp_path / "credentials.json"
    browser_login.save_credentials(path, HOST, make_token_set())

    cleared = browser_login.clear_credentials(path, HOST)

    assert cleared.refresh_token == "wb_rt_stored"
    assert browser_login.load_credentials(path, HOST) is None


def test_clearing_when_not_logged_in(tmp_path: pathlib.Path):
    assert browser_login.clear_credentials(tmp_path / "nope.json", HOST) is None


@pytest.fixture
def browser_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every check in can_open_browser pass, so a test can fail just one."""
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(ipython, "in_jupyter", lambda: False)
    monkeypatch.setattr(util, "_is_databricks", lambda: False)
    monkeypatch.setattr(browser_login.webbrowser, "get", lambda: object())
    monkeypatch.setattr(
        browser_login,
        "sys",
        types.SimpleNamespace(
            platform="linux",
            stdin=types.SimpleNamespace(isatty=lambda: True),
            stderr=types.SimpleNamespace(isatty=lambda: True),
        ),
    )


def _closed_isatty() -> bool:
    raise ValueError("I/O operation on closed file")


def _no_browser() -> object:
    raise webbrowser.Error("could not locate runnable browser")


def test_can_open_browser_when_nothing_prevents_it(browser_available: None):
    assert browser_login.can_open_browser() is True


@pytest.mark.parametrize(
    "prevent",
    [
        pytest.param(
            lambda mp: mp.setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 22"),
            id="ssh-connection",
        ),
        pytest.param(lambda mp: mp.setenv("SSH_TTY", "/dev/pts/0"), id="ssh-tty"),
        pytest.param(
            lambda mp: mp.setattr(ipython, "in_jupyter", lambda: True),
            id="jupyter",
        ),
        pytest.param(
            lambda mp: mp.setattr(util, "_is_databricks", lambda: True),
            id="databricks",
        ),
        pytest.param(
            lambda mp: mp.setattr(browser_login.sys.stdin, "isatty", lambda: False),
            id="stdin-not-a-tty",
        ),
        pytest.param(
            lambda mp: mp.setattr(browser_login.sys.stderr, "isatty", lambda: False),
            id="stderr-not-a-tty",
        ),
        pytest.param(
            lambda mp: mp.setattr(browser_login.sys, "stdin", None),
            id="stdin-is-none",
        ),
        pytest.param(
            lambda mp: mp.setattr(browser_login.sys, "stderr", None),
            id="stderr-is-none",
        ),
        pytest.param(
            lambda mp: mp.setattr(browser_login.sys.stdin, "isatty", _closed_isatty),
            id="stdin-is-closed",
        ),
        pytest.param(
            lambda mp: mp.setattr(browser_login.sys.stderr, "isatty", _closed_isatty),
            id="stderr-is-closed",
        ),
        pytest.param(lambda mp: mp.delenv("DISPLAY"), id="no-display"),
        pytest.param(
            lambda mp: mp.setattr(browser_login.webbrowser, "get", _no_browser),
            id="no-browser",
        ),
    ],
)
def test_can_open_browser_rejects(
    browser_available: None,
    monkeypatch: pytest.MonkeyPatch,
    prevent: Callable[[pytest.MonkeyPatch], None],
):
    prevent(monkeypatch)

    assert browser_login.can_open_browser() is False


def test_revoke_sends_the_refresh_token(oauth_server: FakeOAuthServer):
    oauth_server.body = {}

    browser_login.revoke(host=oauth_server.host, refresh_token="wb_rt_stored")

    [sent] = oauth_server.received
    assert sent["path"] == "/oidc/revoke"
    assert sent["client_id"] == browser_login.CLI_CLIENT_ID
    assert sent["token"] == "wb_rt_stored"
    assert sent["token_type_hint"] == "refresh_token"


def test_revoke_reports_a_failure(oauth_server: FakeOAuthServer):
    oauth_server.status = 500
    oauth_server.body = None

    with pytest.raises(AuthenticationError, match="Failed to log out"):
        browser_login.revoke(host=oauth_server.host, refresh_token="wb_rt_stored")
