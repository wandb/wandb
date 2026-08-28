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


@pytest.fixture
def mock_responses():
    with RequestsMock() as rsps:
        yield rsps


def test_fetch_idp_config(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli-config",
        json={
            "issuer": "https://idp.example.com/realms/acme",
            "client_id": "wandb-cli",
            "scopes": ["openid", "offline_access"],
            "auth_method": "pkce",
        },
    )

    result = sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))

    assert result == sso_login.IdpConfig(
        issuer="https://idp.example.com/realms/acme",
        client_id="wandb-cli",
        scopes=("openid", "offline_access"),
    )


def test_fetch_idp_config_passes_org(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli-config",
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
        "https://my-wandb.example.com/oidc/cli-config",
        json={"issuer": "https://idp.example.com", "client_id": "wandb-cli"},
    )

    result = sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))

    assert result.scopes == sso_login._DEFAULT_SCOPES


def test_fetch_idp_config_not_found(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli-config",
        status=404,
    )

    with pytest.raises(AuthenticationError, match="no CLI SSO login configured"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"), org="acme")


def test_fetch_idp_config_server_error(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli-config",
        status=500,
        body="internal error",
    )

    with pytest.raises(AuthenticationError, match="HTTP 500"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))


def test_fetch_idp_config_invalid_json(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli-config",
        json={"issuer": "https://idp.example.com"},  # missing client_id
    )

    with pytest.raises(AuthenticationError, match="invalid SSO configuration"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))


def test_fetch_idp_config_rejects_insecure_issuer(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://my-wandb.example.com/oidc/cli-config",
        json={"issuer": "http://idp.example.com", "client_id": "wandb-cli"},
    )

    with pytest.raises(AuthenticationError, match="must use HTTPS"):
        sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))


def test_login_rejects_insecure_wandb_host():
    with pytest.raises(AuthenticationError, match="W&B host must use HTTPS"):
        sso_login.login_with_pkce(HostUrl("http://wandb.example.com"))


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


def test_token_set_write_is_private(tmp_path):
    token_set = sso_login.TokenSet(
        id_token="id-token",
        refresh_token="refresh-token",
        token_endpoint="https://idp.example.com/token",
        client_id="wandb-cli",
    )
    path = tmp_path / "nested" / "identity_token.json"
    path.parent.mkdir()
    path.write_text("old")
    path.chmod(0o644)

    token_set.write(path)

    assert path.exists()
    assert (path.stat().st_mode & 0o777) == 0o600
    assert json.loads(path.read_text()) == {
        "id_token": "id-token",
        "refresh_token": "refresh-token",
        "token_endpoint": "https://idp.example.com/token",
        "client_id": "wandb-cli",
    }


def test_default_identity_token_file_uses_config_dir(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("WANDB_CONFIG_DIR", str(tmp_path))

    assert sso_login.default_identity_token_file() == tmp_path / "identity_token.json"


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
        )

    assert len(mock_responses.calls) == 1


def test_authorization_url_contains_pkce_params():
    url = sso_login._authorization_url(
        "https://idp.example.com/authorize",
        client_id="wandb-cli",
        redirect_uri="http://127.0.0.1:12345/callback",
        scopes=("openid", "offline_access"),
        state="test-state",
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
    assert query["code_challenge"] == ["test-challenge"]
    assert query["code_challenge_method"] == ["S256"]


def test_authorization_code_surfaces_idp_error():
    with pytest.raises(AuthenticationError, match="access_denied"):
        sso_login._authorization_code(
            {
                "state": ["s"],
                "error": ["access_denied"],
                "error_description": ["access_denied"],
            },
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

    assert result == sso_login.TokenSet(
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
    redirect_uri = exchange_body["redirect_uri"][0]
    assert redirect_uri.startswith("http://127.0.0.1:")


def test_pkce_login_redirects_browser_to_success_page(
    mock_responses: RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
):
    callback_responses: list[tuple[int, str | None]] = []

    def fake_open(auth_url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
        parsed = urllib.parse.urlsplit(query["redirect_uri"][0])
        params = {"code": "fake-auth-code", "state": query["state"][0]}

        def hit_callback() -> None:
            # http.client does not follow redirects, unlike urllib.request.
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            conn.request("GET", f"{parsed.path}?{urllib.parse.urlencode(params)}")
            response = conn.getresponse()
            callback_responses.append((response.status, response.getheader("Location")))
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
    assert callback_responses == [
        (302, "https://my-wandb.example.com/cli-login-success")
    ]


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
        sso_login.pkce_login(
            idp_config,
            discovery,
            open_browser=False,
            timeout=0.2,
        )
