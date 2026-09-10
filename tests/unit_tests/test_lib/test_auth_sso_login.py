import base64
import hashlib
import http.client
import json
import threading
import urllib.parse
import urllib.request

import pytest
from responses import RequestsMock
from wandb.errors import AuthenticationError
from wandb.sdk.lib.wbauth import sso_login
from wandb.sdk.lib.wbauth.host_url import HostUrl
from wandb.sdk.lib.wbauth.identity_token_file import Account


@pytest.fixture
def mock_responses():
    with RequestsMock() as rsps:
        yield rsps


@pytest.fixture(autouse=True)
def headless(monkeypatch: pytest.MonkeyPatch):
    """Stands in for a machine with no browser, unless a test says otherwise."""
    monkeypatch.setattr(sso_login.webbrowser, "open", lambda url: False)


def _fake_id_token(**claims: str) -> str:
    """Builds an unsigned JWT, which is all the login flow reads."""

    def segment(value: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(value).encode())
        return raw.rstrip(b"=").decode()

    return f"{segment({'alg': 'none'})}.{segment(claims)}.signature"


def test_fetch_idp_config(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={
            "issuer": "https://idp.example.com/realms/acme",
            "client_id": "wandb-cli",
            "scopes": ["openid", "offline_access"],
            "auth_methods": ["pkce", "device_code"],
        },
    )

    result = sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))

    assert result == sso_login.IdpConfig(
        issuer="https://idp.example.com/realms/acme",
        client_id="wandb-cli",
        scopes=("openid", "offline_access"),
        auth_methods=("pkce", "device_code"),
    )


def test_fetch_idp_config_reads_legacy_singular_auth_method(
    mock_responses: RequestsMock,
):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={
            "issuer": "https://idp.example.com",
            "client_id": "wandb-cli",
            "auth_method": "pkce",
        },
    )

    result = sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))

    assert result.auth_methods == ("pkce",)


def test_fetch_idp_config_without_auth_methods(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={"issuer": "https://idp.example.com", "client_id": "wandb-cli"},
    )

    result = sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))

    assert result.auth_methods is None


def test_fetch_idp_config_rejects_malformed_auth_methods(
    mock_responses: RequestsMock,
):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={
            "issuer": "https://idp.example.com",
            "client_id": "wandb-cli",
            "auth_methods": "pkce",
        },
    )

    with pytest.raises(AuthenticationError, match="auth_methods"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))


def test_fetch_idp_config_passes_org(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={"issuer": "https://idp.example.com", "client_id": "wandb-cli"},
    )

    sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"), org="acme")

    request_url = mock_responses.calls[0].request.url
    assert urllib.parse.parse_qs(urllib.parse.urlparse(request_url).query) == {
        "organization": ["acme"]
    }


def test_fetch_idp_config_defaults_scopes(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={"issuer": "https://idp.example.com", "client_id": "wandb-cli"},
    )

    result = sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))

    assert result.scopes == sso_login._DEFAULT_SCOPES


def test_fetch_idp_config_not_found(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        status=404,
    )

    with pytest.raises(AuthenticationError, match="no CLI SSO login configured"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"), org="acme")


def test_fetch_idp_config_server_error(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        status=500,
        body="internal error",
    )

    with pytest.raises(AuthenticationError, match="HTTP 500"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))


def test_fetch_idp_config_invalid_json(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={"issuer": "https://idp.example.com"},  # missing client_id
    )

    with pytest.raises(AuthenticationError, match="invalid SSO configuration"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))


def test_fetch_idp_config_rejects_insecure_issuer(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={"issuer": "http://idp.example.com", "client_id": "wandb-cli"},
    )

    with pytest.raises(AuthenticationError, match="must use HTTPS"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("http://127.0.0.1:8080/token", True),
        ("http://127.0.0.2:8080/token", True),
        ("http://localhost:8080/token", True),
        ("http://[::1]:8080/token", True),
        ("http://10.0.0.1:8080/token", False),
        ("http://idp.example.com/token", False),
    ],
)
def test_secure_url_allows_plain_http_only_on_loopback(url: str, allowed: bool):
    if allowed:
        assert sso_login._secure_url(url, name="token_endpoint") == url
    else:
        with pytest.raises(ValueError, match="must use HTTPS"):
            sso_login._secure_url(url, name="token_endpoint")


def test_login_with_pkce_requires_server_support(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={
            "issuer": "https://idp.example.com",
            "client_id": "wandb-cli",
            "auth_methods": ["device_code"],
        },
    )

    with pytest.raises(AuthenticationError, match="does not offer browser login"):
        sso_login.login_with_pkce(HostUrl("https://my-wandb.example.com"))


def test_discover_oidc(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://idp.example.com/.well-known/openid-configuration",
        json={
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
        },
    )

    result = sso_login.discover_oidc("https://idp.example.com")

    assert result == sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
    )


def test_discover_oidc_rejects_insecure_device_endpoint(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://idp.example.com/.well-known/openid-configuration",
        json={
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "device_authorization_endpoint": "http://idp.example.com/device",
        },
    )

    with pytest.raises(AuthenticationError, match="must use HTTPS"):
        sso_login.discover_oidc("https://idp.example.com")


def test_discover_oidc_missing_endpoint(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://idp.example.com/.well-known/openid-configuration",
        json={
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/authorize",
        },
    )

    with pytest.raises(AuthenticationError, match="invalid OIDC discovery document"):
        sso_login.discover_oidc("https://idp.example.com")


def test_discover_oidc_rejects_issuer_mismatch(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://idp.example.com/.well-known/openid-configuration",
        json={
            "issuer": "https://attacker.example.com",
            "authorization_endpoint": "https://attacker.example.com/authorize",
            "token_endpoint": "https://attacker.example.com/token",
        },
    )

    with pytest.raises(AuthenticationError, match="does not match"):
        sso_login.discover_oidc("https://idp.example.com")


def test_exchange_code_requires_refresh_token(mock_responses: RequestsMock):
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "id-token"},
    )

    with pytest.raises(AuthenticationError, match="refresh token"):
        sso_login._exchange_code(
            "https://idp.example.com/token",
            client_id="wandb-cli",
            code="code",
            redirect_uri="http://127.0.0.1/callback",
            code_verifier="verifier",
            nonce="test-nonce",
        )


def test_exchange_code_does_not_follow_redirect(mock_responses: RequestsMock):
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        status=307,
        headers={"Location": "https://attacker.example.com/token"},
    )

    with pytest.raises(AuthenticationError, match="HTTP 307"):
        sso_login._exchange_code(
            "https://idp.example.com/token",
            client_id="wandb-cli",
            code="code",
            redirect_uri="http://127.0.0.1/callback",
            code_verifier="verifier",
            nonce="test-nonce",
        )

    assert len(mock_responses.calls) == 1


def test_exchange_code_rejects_mismatched_nonce(mock_responses: RequestsMock):
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={
            "id_token": _fake_id_token(nonce="someone-elses-nonce"),
            "refresh_token": "refresh-token",
        },
    )

    with pytest.raises(AuthenticationError, match="a different login request"):
        sso_login._exchange_code(
            "https://idp.example.com/token",
            client_id="wandb-cli",
            code="code",
            redirect_uri="http://127.0.0.1/callback",
            code_verifier="verifier",
            nonce="test-nonce",
        )


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"nonce": "test-nonce"}, id="matching nonce"),
        # Omitting the claim is out of spec, but common enough that
        # failing the login over it would do more harm than good.
        pytest.param({}, id="no nonce"),
    ],
)
def test_exchange_code_accepts_id_token(
    mock_responses: RequestsMock,
    claims: dict,
):
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": _fake_id_token(**claims), "refresh_token": "refresh-token"},
    )

    account = sso_login._exchange_code(
        "https://idp.example.com/token",
        client_id="wandb-cli",
        code="code",
        redirect_uri="http://127.0.0.1/callback",
        code_verifier="verifier",
        nonce="test-nonce",
    )

    assert account.refresh_token == "refresh-token"


def test_authorization_url_contains_pkce_params():
    url = sso_login._authorization_url(
        "https://idp.example.com/authorize",
        client_id="wandb-cli",
        redirect_uri="http://127.0.0.1:12345/callback",
        scopes=("openid", "offline_access"),
        state="test-state",
        nonce="test-nonce",
        code_challenge="test-challenge",
    )

    parsed = urllib.parse.urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "idp.example.com"
    assert parsed.path == "/authorize"
    query = urllib.parse.parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["wandb-cli"]
    assert query["redirect_uri"] == ["http://127.0.0.1:12345/callback"]
    assert query["scope"] == ["openid offline_access"]
    assert query["state"] == ["test-state"]
    assert query["nonce"] == ["test-nonce"]
    assert query["code_challenge"] == ["test-challenge"]
    assert query["code_challenge_method"] == ["S256"]


def test_authorization_code_surfaces_idp_error():
    with pytest.raises(AuthenticationError, match="Consent required"):
        sso_login._authorization_code(
            {"error": ["access_denied"], "error_description": ["Consent required"]},
            expected_state="s",
        )


def test_authorization_code_requires_code():
    with pytest.raises(
        AuthenticationError, match="did not include an authorization code"
    ):
        sso_login._authorization_code({"state": ["s"]}, expected_state="s")


def _simulate_browser_hitting_callback(
    monkeypatch: pytest.MonkeyPatch,
    *,
    code: str = "fake-auth-code",
    omit_state: bool = False,
) -> list[str]:
    """Makes webbrowser.open() redirect to the loopback callback."""
    opened_urls: list[str] = []

    def fake_open(auth_url: str) -> bool:
        opened_urls.append(auth_url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
        redirect_uri = query["redirect_uri"][0]
        params = {"code": code}
        if not omit_state:
            params["state"] = query["state"][0]

        def hit_callback() -> None:
            url = f"{redirect_uri}?{urllib.parse.urlencode(params)}"
            urllib.request.urlopen(url, timeout=5)

        threading.Thread(target=hit_callback, daemon=True).start()
        return True

    monkeypatch.setattr(sso_login.webbrowser, "open", fake_open)
    return opened_urls


def test_pkce_login_full_flow(
    mock_responses: RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
):
    opened_urls = _simulate_browser_hitting_callback(monkeypatch, code="fake-auth-code")
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "fake-id-token", "refresh_token": "fake-refresh-token"},
    )

    idp_config = sso_login.IdpConfig(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
        scopes=("openid", "offline_access"),
    )
    discovery = sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
    )

    result = sso_login.pkce_login(idp_config, discovery, timeout=10)

    assert result == Account(
        id_token="fake-id-token",
        refresh_token="fake-refresh-token",
        token_endpoint="https://idp.example.com/token",
        client_id="wandb-cli",
    )

    exchange_body = urllib.parse.parse_qs(mock_responses.calls[0].request.body)
    assert exchange_body["grant_type"] == ["authorization_code"]
    assert exchange_body["code"] == ["fake-auth-code"]
    assert exchange_body["client_id"] == ["wandb-cli"]
    verifier = exchange_body["code_verifier"][0]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    auth_query = urllib.parse.parse_qs(urllib.parse.urlparse(opened_urls[0]).query)
    assert auth_query["code_challenge"] == [challenge]
    assert auth_query["nonce"]
    redirect_uri = exchange_body["redirect_uri"][0]
    assert redirect_uri.startswith("http://127.0.0.1:")


def test_pkce_login_redirects_browser_to_success_page(
    mock_responses: RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
):
    callback_responses: list[http.client.HTTPResponse] = []

    def fake_open(auth_url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
        parsed = urllib.parse.urlsplit(query["redirect_uri"][0])
        params = {"code": "fake-auth-code", "state": query["state"][0]}

        def hit_callback() -> None:
            # http.client does not follow redirects, unlike urllib.request.
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            conn.request("GET", f"{parsed.path}?{urllib.parse.urlencode(params)}")
            callback_responses.append(conn.getresponse())
            conn.close()

        threading.Thread(target=hit_callback, daemon=True).start()
        return True

    monkeypatch.setattr(sso_login.webbrowser, "open", fake_open)
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "fake-id-token", "refresh_token": "fake-refresh-token"},
    )

    idp_config = sso_login.IdpConfig(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
        scopes=("openid", "offline_access"),
    )
    discovery = sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
    )

    result = sso_login.pkce_login(
        idp_config,
        discovery,
        timeout=10,
        success_redirect_url="https://my-wandb.example.com/cli-login-success",
    )

    assert result.id_token == "fake-id-token"
    (response,) = callback_responses
    assert response.status == 302
    assert response.getheader("Location") == (
        "https://my-wandb.example.com/cli-login-success"
    )
    # The URL being left carries the authorization code.
    assert response.getheader("Referrer-Policy") == "no-referrer"


def test_pkce_login_rejects_mismatched_state(
    mock_responses: RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
):
    _simulate_browser_hitting_callback(monkeypatch, omit_state=True)

    idp_config = sso_login.IdpConfig(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
        scopes=("openid",),
    )
    discovery = sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
    )

    with pytest.raises(AuthenticationError, match="state did not match"):
        sso_login.pkce_login(idp_config, discovery, timeout=10)

    assert len(mock_responses.calls) == 0


def test_pkce_login_times_out_without_a_callback():
    idp_config = sso_login.IdpConfig(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
        scopes=("openid",),
    )
    discovery = sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
    )

    with pytest.raises(TimeoutError):
        sso_login.pkce_login(idp_config, discovery, timeout=0.2)


@pytest.fixture
def device_idp_config() -> sso_login.IdpConfig:
    return sso_login.IdpConfig(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
        scopes=("openid", "offline_access"),
        auth_methods=("pkce", "device_code"),
    )


@pytest.fixture
def device_discovery() -> sso_login.OidcDiscovery:
    return sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
        device_authorization_endpoint="https://idp.example.com/device",
    )


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Records poll waits instead of actually sleeping through them."""
    waits: list[float] = []
    monkeypatch.setattr(sso_login.time, "sleep", waits.append)
    return waits


def _add_device_authorization(
    mock_responses: RequestsMock,
    **overrides: object,
) -> None:
    mock_responses.add(
        "POST",
        "https://idp.example.com/device",
        json={
            "device_code": "fake-device-code",
            "user_code": "WDBX-1234",
            "verification_uri": "https://idp.example.com/activate",
            "expires_in": 600,
            "interval": 5,
            **overrides,
        },
    )


def test_device_code_login_full_flow(
    mock_responses: RequestsMock,
    device_idp_config: sso_login.IdpConfig,
    device_discovery: sso_login.OidcDiscovery,
    slept: list[float],
    capsys: pytest.CaptureFixture,
):
    _add_device_authorization(mock_responses)
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"error": "authorization_pending"},
        status=400,
    )
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "fake-id-token", "refresh_token": "fake-refresh-token"},
    )

    result = sso_login.device_code_login(device_idp_config, device_discovery)

    assert result == Account(
        id_token="fake-id-token",
        refresh_token="fake-refresh-token",
        token_endpoint="https://idp.example.com/token",
        client_id="wandb-cli",
    )
    assert slept == [5.0, 5.0]

    output = capsys.readouterr().err
    assert "https://idp.example.com/activate" in output
    assert "WDBX-1234" in output

    device_request = urllib.parse.parse_qs(mock_responses.calls[0].request.body)
    assert device_request["client_id"] == ["wandb-cli"]
    assert device_request["scope"] == ["openid offline_access"]

    poll_request = urllib.parse.parse_qs(mock_responses.calls[1].request.body)
    assert poll_request["grant_type"] == [
        "urn:ietf:params:oauth:grant-type:device_code"
    ]
    assert poll_request["device_code"] == ["fake-device-code"]
    assert poll_request["client_id"] == ["wandb-cli"]


def test_device_code_login_opens_browser_to_complete_uri(
    mock_responses: RequestsMock,
    device_idp_config: sso_login.IdpConfig,
    device_discovery: sso_login.OidcDiscovery,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
):
    _add_device_authorization(
        mock_responses,
        verification_uri_complete="https://idp.example.com/activate?user_code=WDBX-1234",
    )
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "fake-id-token", "refresh_token": "fake-refresh-token"},
    )

    opened_urls: list[str] = []
    monkeypatch.setattr(
        sso_login.webbrowser, "open", lambda url: opened_urls.append(url) or True
    )

    sso_login.device_code_login(device_idp_config, device_discovery)

    assert opened_urls == ["https://idp.example.com/activate?user_code=WDBX-1234"]
    output = capsys.readouterr().err
    assert "Opened https://idp.example.com/activate?user_code=WDBX-1234" in output
    assert "WDBX-1234" in output


def test_device_code_login_falls_back_when_browser_fails_to_open(
    mock_responses: RequestsMock,
    device_idp_config: sso_login.IdpConfig,
    device_discovery: sso_login.OidcDiscovery,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
):
    _add_device_authorization(mock_responses)
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "fake-id-token", "refresh_token": "fake-refresh-token"},
    )

    def fake_open(url: str) -> bool:
        raise sso_login.webbrowser.Error("no browser found")

    monkeypatch.setattr(sso_login.webbrowser, "open", fake_open)

    sso_login.device_code_login(device_idp_config, device_discovery)

    output = capsys.readouterr().err
    assert "Open this URL to log in:" in output
    assert "https://idp.example.com/activate" in output
    assert "WDBX-1234" in output


def test_device_code_login_backs_off_on_slow_down(
    mock_responses: RequestsMock,
    device_idp_config: sso_login.IdpConfig,
    device_discovery: sso_login.OidcDiscovery,
    slept: list[float],
):
    _add_device_authorization(mock_responses)
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"error": "slow_down"},
        status=400,
    )
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "fake-id-token", "refresh_token": "fake-refresh-token"},
    )

    sso_login.device_code_login(device_idp_config, device_discovery)

    assert slept == [5.0, 10.0]


@pytest.mark.parametrize(
    ("error", "message"),
    [
        ("access_denied", "the request was denied"),
        ("expired_token", "the code expired"),
        ("invalid_client", "HTTP 400"),
    ],
)
def test_device_code_login_surfaces_idp_errors(
    mock_responses: RequestsMock,
    device_idp_config: sso_login.IdpConfig,
    device_discovery: sso_login.OidcDiscovery,
    slept: list[float],
    error: str,
    message: str,
):
    _add_device_authorization(mock_responses)
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"error": error},
        status=400,
    )

    with pytest.raises(AuthenticationError, match=message):
        sso_login.device_code_login(device_idp_config, device_discovery)


def test_device_code_login_times_out(
    mock_responses: RequestsMock,
    device_idp_config: sso_login.IdpConfig,
    device_discovery: sso_login.OidcDiscovery,
    slept: list[float],
):
    _add_device_authorization(mock_responses, expires_in=0)

    with pytest.raises(AuthenticationError, match="Timed out"):
        sso_login.device_code_login(device_idp_config, device_discovery)

    # The code was already expired, so it never polled.
    assert len(mock_responses.calls) == 1


def test_device_code_login_requires_a_device_endpoint(
    device_idp_config: sso_login.IdpConfig,
):
    discovery = sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
    )

    with pytest.raises(AuthenticationError, match="does not support device code"):
        sso_login.device_code_login(device_idp_config, discovery)


def test_device_code_login_rejects_malformed_authorization(
    mock_responses: RequestsMock,
    device_idp_config: sso_login.IdpConfig,
    device_discovery: sso_login.OidcDiscovery,
):
    mock_responses.add(
        "POST",
        "https://idp.example.com/device",
        json={"device_code": "fake-device-code"},  # missing user_code
    )

    with pytest.raises(
        AuthenticationError, match="invalid device authorization response"
    ):
        sso_login.device_code_login(device_idp_config, device_discovery)


def test_login_with_device_code_requires_server_support(
    mock_responses: RequestsMock,
):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={
            "issuer": "https://idp.example.com",
            "client_id": "wandb-cli",
            "auth_methods": ["pkce"],
        },
    )

    with pytest.raises(AuthenticationError, match="does not offer device code login"):
        sso_login.login_with_device_code(HostUrl("https://my-wandb.example.com"))


def test_login_with_device_code_records_host_and_org(
    mock_responses: RequestsMock,
    slept: list[float],
):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli_config",
        json={
            "issuer": "https://idp.example.com",
            "client_id": "wandb-cli",
            "auth_methods": ["pkce", "device_code"],
        },
    )
    mock_responses.add(
        "GET",
        "https://idp.example.com/.well-known/openid-configuration",
        json={
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "device_authorization_endpoint": "https://idp.example.com/device",
        },
    )
    _add_device_authorization(mock_responses)
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "fake-id-token", "refresh_token": "fake-refresh-token"},
    )

    result = sso_login.login_with_device_code(
        HostUrl("https://my-wandb.example.com"),
        org="acme",
    )

    assert result.host == "https://my-wandb.example.com"
    assert result.org == "acme"
    assert result.id_token == "fake-id-token"
