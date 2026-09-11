import base64
import hashlib
import http.client
import json
import re
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
            "auth_methods": ["pkce"],
        },
    )

    result = sso_login.fetch_idp_config(HostUrl("https://my-wandb.example.com"))

    assert result == sso_login.IdpConfig(
        issuer="https://idp.example.com/realms/acme",
        client_id="wandb-cli",
        scopes=("openid", "offline_access"),
        auth_methods=("pkce",),
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
            "auth_methods": ["unsupported"],
        },
    )

    with pytest.raises(AuthenticationError, match="does not offer browser login"):
        sso_login.login_with_pkce(HostUrl("https://my-wandb.example.com"))


def _add_cli_config(mock_responses: RequestsMock, **overrides: object) -> None:
    mock_responses.add(
        "GET",
        "https://api.wandb.ai/oidc/cli_config",
        json={
            "issuer": "https://idp.example.com",
            "client_id": "wandb-cli",
            **overrides,
        },
    )


@pytest.mark.parametrize(
    ("registered", "named", "message"),
    [
        (
            {"issuer": "https://idp.example.com"},
            {"issuer": "https://acme-login.example"},
            "its issuer is 'https://idp.example.com'",
        ),
        (
            {"client_id": "wandb-cli"},
            {"client_id": "attacker-cli"},
            "its client ID is 'wandb-cli'",
        ),
    ],
)
def test_login_with_pkce_aborts_on_a_provider_the_org_did_not_register(
    mock_responses: RequestsMock,
    registered: dict,
    named: dict,
    message: str,
):
    _add_cli_config(mock_responses, **registered)
    expected = sso_login.ExpectedIdp(
        **{"issuer": "https://idp.example.com", "client_id": "wandb-cli", **named}
    )

    with pytest.raises(AuthenticationError, match=re.escape(message)):
        sso_login.login_with_pkce(
            HostUrl("https://api.wandb.ai"),
            org="acme",
            expected=expected,
        )

    # Nothing beyond the W&B discovery call was attempted.
    assert len(mock_responses.calls) == 1


def test_check_expected_idp_ignores_a_trailing_slash():
    sso_login.check_expected_idp(
        sso_login.IdpConfig(
            issuer="https://idp.example.com/",
            client_id="wandb-cli",
            scopes=("openid",),
        ),
        sso_login.ExpectedIdp(
            issuer="https://idp.example.com",
            client_id="wandb-cli",
        ),
        org="acme",
    )


def test_check_expected_idp_names_both_mismatched_fields():
    with pytest.raises(AuthenticationError) as excinfo:
        sso_login.check_expected_idp(
            sso_login.IdpConfig(
                issuer="https://idp.example.com",
                client_id="wandb-cli",
                scopes=("openid",),
            ),
            sso_login.ExpectedIdp(
                issuer="https://acme-login.example",
                client_id="attacker-cli",
            ),
            org="acme",
        )

    assert "issuer" in str(excinfo.value)
    assert "client ID" in str(excinfo.value)


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


def test_discover_oidc_reads_iss_parameter_support(mock_responses: RequestsMock):
    mock_responses.add(
        "GET",
        "https://idp.example.com/.well-known/openid-configuration",
        json={
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "authorization_response_iss_parameter_supported": True,
        },
    )

    result = sso_login.discover_oidc("https://idp.example.com")

    assert result.iss_parameter_supported


def test_discover_oidc_rejects_malformed_iss_parameter_support(
    mock_responses: RequestsMock,
):
    mock_responses.add(
        "GET",
        "https://idp.example.com/.well-known/openid-configuration",
        json={
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "authorization_response_iss_parameter_supported": "yes",
        },
    )

    with pytest.raises(AuthenticationError, match="must be a boolean"):
        sso_login.discover_oidc("https://idp.example.com")


def test_authorization_code_accepts_matching_iss():
    code = sso_login._authorization_code(
        {"state": ["s"], "code": ["c"], "iss": ["https://idp.example.com/"]},
        expected_state="s",
        expected_issuer="https://idp.example.com",
    )

    assert code == "c"


def test_authorization_code_rejects_foreign_iss():
    with pytest.raises(AuthenticationError, match="attacker.example.com"):
        sso_login._authorization_code(
            {"state": ["s"], "code": ["c"], "iss": ["https://attacker.example.com"]},
            expected_state="s",
            expected_issuer="https://idp.example.com",
        )


def test_authorization_code_tolerates_missing_iss():
    code = sso_login._authorization_code(
        {"state": ["s"], "code": ["c"]},
        expected_state="s",
        expected_issuer="https://idp.example.com",
    )

    assert code == "c"


def test_authorization_code_requires_iss_when_advertised():
    with pytest.raises(AuthenticationError, match="did not"):
        sso_login._authorization_code(
            {"state": ["s"], "code": ["c"]},
            expected_state="s",
            expected_issuer="https://idp.example.com",
            require_issuer=True,
        )


def test_authorization_code_surfaces_idp_error_before_checking_iss():
    with pytest.raises(AuthenticationError, match="Consent required"):
        sso_login._authorization_code(
            {
                "error": ["access_denied"],
                "error_description": ["Consent required"],
                "iss": ["https://attacker.example.com"],
            },
            expected_state="s",
            expected_issuer="https://idp.example.com",
        )


def test_pkce_login_rejects_response_from_another_issuer(
    mock_responses: RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
):
    _simulate_browser_hitting_callback(
        monkeypatch,
        extra_params={"iss": "https://attacker.example.com"},
    )

    idp_config = sso_login.IdpConfig(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
        scopes=("openid",),
    )
    discovery = sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
    )

    with pytest.raises(AuthenticationError, match="attacker.example.com"):
        sso_login.pkce_login(idp_config, discovery, timeout=10)

    # The code never reached the token endpoint.
    assert len(mock_responses.calls) == 0


def test_pkce_login_accepts_response_carrying_its_own_issuer(
    mock_responses: RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
):
    _simulate_browser_hitting_callback(
        monkeypatch,
        extra_params={"iss": "https://idp.example.com"},
    )
    mock_responses.add(
        "POST",
        "https://idp.example.com/token",
        json={"id_token": "fake-id-token", "refresh_token": "fake-refresh-token"},
    )

    idp_config = sso_login.IdpConfig(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
        scopes=("openid",),
    )
    discovery = sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
        iss_parameter_supported=True,
    )

    result = sso_login.pkce_login(idp_config, discovery, timeout=10)

    assert result.id_token == "fake-id-token"


def test_pkce_login_requires_iss_from_an_idp_that_advertises_it(
    mock_responses: RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
):
    _simulate_browser_hitting_callback(monkeypatch)

    idp_config = sso_login.IdpConfig(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
        scopes=("openid",),
    )
    discovery = sso_login.OidcDiscovery(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
        iss_parameter_supported=True,
    )

    with pytest.raises(AuthenticationError, match="identifies itself"):
        sso_login.pkce_login(idp_config, discovery, timeout=10)

    assert len(mock_responses.calls) == 0


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
    extra_params: dict[str, str] | None = None,
) -> list[str]:
    """Makes webbrowser.open() redirect to the loopback callback."""
    opened_urls: list[str] = []

    def fake_open(auth_url: str) -> bool:
        opened_urls.append(auth_url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
        redirect_uri = query["redirect_uri"][0]
        params = {"code": code, **(extra_params or {})}
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
    assert redirect_uri.startswith("http://localhost:")


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
