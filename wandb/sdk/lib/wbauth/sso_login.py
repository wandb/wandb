"""Browser-based OIDC login for `wandb login sso`."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import tempfile
import time
import urllib.parse
import webbrowser
from collections.abc import Sequence

import requests

from wandb import env
from wandb.errors import AuthenticationError, term

from .host_url import HostUrl

_DEFAULT_SCOPES = ("openid", "profile", "email", "offline_access")
_LOGIN_TIMEOUT_SECONDS = 300.0


def default_identity_token_file() -> pathlib.Path:
    """Returns the identity-token path in the configured W&B config directory."""
    config_dir = os.getenv(env.CONFIG_DIR, "~/.config/wandb")
    return pathlib.Path(config_dir).expanduser() / "identity_token.json"


@dataclasses.dataclass(frozen=True)
class IdpConfig:
    """IdP connection details returned by `GET /oidc/cli-config`."""

    issuer: str
    client_id: str
    scopes: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class OidcDiscovery:
    """OIDC endpoints used by the PKCE flow."""

    authorization_endpoint: str
    token_endpoint: str


@dataclasses.dataclass(frozen=True)
class TokenSet:
    """Credentials and metadata needed to refresh an OIDC ID token."""

    id_token: str
    refresh_token: str
    token_endpoint: str
    client_id: str
    host: str = ""

    def write(self, path: str | os.PathLike[str]) -> None:
        """Atomically writes credentials to a user-only file."""
        resolved = pathlib.Path(path).expanduser()
        resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        contents = {
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "token_endpoint": self.token_endpoint,
            "client_id": self.client_id,
        }
        if self.host:
            contents["host"] = self.host
        data = json.dumps(contents, indent=2)

        fd, temp_path = tempfile.mkstemp(
            dir=resolved.parent, prefix=f".{resolved.name}."
        )
        try:
            with os.fdopen(fd, "w") as file:
                file.write(data)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, resolved)
        finally:
            pathlib.Path(temp_path).unlink(missing_ok=True)


def _parse_idp_config(body: object) -> IdpConfig:
    if not isinstance(body, dict):
        raise TypeError("response must be an object")

    issuer = _secure_url(body["issuer"], name="issuer", allow_query=False)
    client_id = body["client_id"]
    scopes = body.get("scopes") or _DEFAULT_SCOPES
    if not isinstance(client_id, str) or not client_id:
        raise TypeError("client_id must be a non-empty string")
    if (
        not isinstance(scopes, (list, tuple))
        or not scopes
        or not all(isinstance(scope, str) and scope for scope in scopes)
    ):
        raise TypeError("scopes must be a non-empty list of strings")
    if "openid" not in scopes:
        raise ValueError("scopes must include 'openid'")
    if body.get("auth_method", "pkce") != "pkce":
        raise ValueError("only the 'pkce' auth_method is supported")

    return IdpConfig(issuer=issuer, client_id=client_id, scopes=tuple(scopes))


def _parse_discovery(body: object, *, issuer: str) -> OidcDiscovery:
    if not isinstance(body, dict):
        raise TypeError("response must be an object")

    discovered_issuer = _secure_url(
        body["issuer"], name="discovery issuer", allow_query=False
    )
    if discovered_issuer.rstrip("/") != issuer:
        raise ValueError(
            f"discovery issuer {discovered_issuer!r} does not match {issuer!r}"
        )
    return OidcDiscovery(
        authorization_endpoint=_secure_url(
            body["authorization_endpoint"], name="authorization_endpoint"
        ),
        token_endpoint=_secure_url(body["token_endpoint"], name="token_endpoint"),
    )


def fetch_idp_config(host: HostUrl, *, org: str | None = None) -> IdpConfig:
    """Fetches the host's CLI SSO configuration."""
    try:
        _secure_url(host.url, name="W&B host")
    except (TypeError, ValueError) as e:
        raise AuthenticationError(str(e)) from None
    url = f"{host.url}/oidc/cli-config"

    try:
        response = requests.get(
            url,
            params={"organization": org} if org else None,
            timeout=env.get_http_timeout(10),
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise AuthenticationError(f"Failed to reach {host}: {e}") from None

    if response.status_code == 404:
        raise AuthenticationError(
            f"{host} has no CLI SSO login configured"
            + (f" for organization {org!r}" if org else "")
            + ". Ask a W&B admin to configure it under Org Settings ->"
            + " Authentication -> 'CLI login (SSO)', or pass --org if you"
            + " belong to more than one organization."
        )
    if response.status_code != 200:
        raise AuthenticationError(
            f"Failed to fetch the SSO configuration from {host}:"
            f" HTTP {response.status_code}: {response.text}"
        )

    try:
        return _parse_idp_config(response.json())
    except (ValueError, KeyError, TypeError) as e:
        raise AuthenticationError(
            f"{host} returned an invalid SSO configuration: {e}"
        ) from None


def discover_oidc(issuer: str) -> OidcDiscovery:
    """Fetches and validates the IdP's OIDC discovery document."""
    issuer = _secure_url(issuer, name="issuer", allow_query=False).rstrip("/")
    url = f"{issuer}/.well-known/openid-configuration"

    try:
        response = requests.get(
            url,
            timeout=env.get_http_timeout(10),
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise AuthenticationError(
            f"Failed to reach the identity provider at {issuer}: {e}"
        ) from None

    if response.status_code != 200:
        raise AuthenticationError(
            f"Failed to fetch the OIDC discovery document from {issuer}:"
            f" HTTP {response.status_code}: {response.text}"
        )

    try:
        return _parse_discovery(response.json(), issuer=issuer)
    except (ValueError, KeyError, TypeError) as e:
        raise AuthenticationError(
            f"{issuer} returned an invalid OIDC discovery document: {e}"
        ) from None


def login_with_pkce(
    host: HostUrl,
    *,
    org: str | None = None,
    open_browser: bool = True,
) -> TokenSet:
    """Runs discovery and an Authorization Code + PKCE login."""
    idp_config = fetch_idp_config(host, org=org)
    discovery = discover_oidc(idp_config.issuer)
    return dataclasses.replace(
        pkce_login(
            idp_config,
            discovery,
            open_browser=open_browser,
            success_redirect_url=f"{host.url}/cli-login-success",
        ),
        host=host.url,
    )


def pkce_login(
    idp_config: IdpConfig,
    discovery: OidcDiscovery,
    *,
    open_browser: bool = True,
    timeout: float = _LOGIN_TIMEOUT_SECONDS,
    success_redirect_url: str | None = None,
) -> TokenSet:
    """Performs an Authorization Code + PKCE login on a loopback server.

    If `success_redirect_url` is set, a successful callback redirects the
    browser there (the W&B app's CLI-login landing page); otherwise, and on
    error callbacks, a minimal inline notice page is served.
    """
    code_verifier, code_challenge = _new_pkce_pair()
    state = secrets.token_urlsafe(24)

    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.callback_params = None  # type: ignore[attr-defined]
    server.success_redirect_url = success_redirect_url  # type: ignore[attr-defined]
    server.expected_state = state  # type: ignore[attr-defined]
    try:
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/callback"

        auth_url = _authorization_url(
            discovery.authorization_endpoint,
            client_id=idp_config.client_id,
            redirect_uri=redirect_uri,
            scopes=idp_config.scopes,
            state=state,
            code_challenge=code_challenge,
        )

        opened = False
        if open_browser:
            try:
                opened = webbrowser.open(auth_url)
            except webbrowser.Error:
                opened = False

        if opened:
            term.termlog(f"Opened {auth_url} in your browser.")
        else:
            term.termlog(f"Open this URL to log in:\n{auth_url}")

        params = _wait_for_callback(server, timeout=timeout)
    finally:
        server.server_close()

    code = _authorization_code(params, expected_state=state)

    return _exchange_code(
        discovery.token_endpoint,
        client_id=idp_config.client_id,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )


def _new_pkce_pair() -> tuple[str, str]:
    """Returns a (code_verifier, code_challenge) pair, per RFC 7636 section 4."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _authorization_url(
    endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    state: str,
    code_challenge: str,
) -> str:
    """Builds the IdP authorization URL for the loopback PKCE flow."""
    parsed = urllib.parse.urlsplit(endpoint)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }.items()
    )
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


_CALLBACK_HTML = """\
<!DOCTYPE html>
<title>W&B SSO login</title>
<body style="font-family: sans-serif; text-align: center; margin-top: 15%">
<h2>Authentication response received.</h2>
<p>Return to the terminal to finish logging in.</p>
</body>
"""


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Handles the IdP's redirect to the PKCE loopback server."""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        self.server.callback_params = params  # type: ignore[attr-defined]

        redirect_url = getattr(self.server, "success_redirect_url", None)
        looks_successful = (
            "error" not in params
            and params.get("code")
            and params.get("state") == [getattr(self.server, "expected_state", None)]
        )
        if redirect_url and looks_successful:
            self.send_response(302)
            self.send_header("Location", redirect_url)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        body = _CALLBACK_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def _wait_for_callback(
    server: http.server.HTTPServer,
    *,
    timeout: float,
) -> dict[str, list[str]]:
    """Blocks until the loopback server receives the IdP's redirect."""
    deadline = time.monotonic() + timeout

    while getattr(server, "callback_params", None) is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Timed out waiting for the SSO login to complete in the browser."
            )
        server.timeout = remaining
        server.handle_request()

    return server.callback_params  # type: ignore[attr-defined]


def _authorization_code(params: dict[str, list[str]], *, expected_state: str) -> str:
    """Extracts and validates the authorization code."""
    if (state := params.get("state", [None])[0]) != expected_state:
        raise AuthenticationError(
            "SSO login failed: the redirect's state did not match the"
            " request. Please try again." + (f" (got {state!r})" if state else "")
        )

    if error := params.get("error", [None])[0]:
        description = params.get("error_description", [error])[0]
        raise AuthenticationError(f"SSO login failed: {description}")

    if not (code := params.get("code", [None])[0]):
        raise AuthenticationError(
            "SSO login failed: the identity provider's redirect did not"
            " include an authorization code."
        )

    return code


def _parse_token_response(body: object) -> tuple[str, str]:
    if not isinstance(body, dict):
        raise TypeError("response must be an object")

    id_token = body["id_token"]
    refresh_token = body["refresh_token"]
    if not isinstance(id_token, str) or not id_token:
        raise TypeError("id_token must be a non-empty string")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise TypeError("refresh_token must be a non-empty string")
    return id_token, refresh_token


def _exchange_code(
    token_endpoint: str,
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> TokenSet:
    """Exchanges an authorization code for tokens (RFC 6749 section 4.1.3)."""
    try:
        response = requests.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            timeout=env.get_http_timeout(10),
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise AuthenticationError(
            f"Failed to reach the identity provider at {token_endpoint}: {e}"
        ) from None

    if response.status_code != 200:
        detail = f"HTTP {response.status_code}"
        try:
            error = response.json()
            description = error.get("error_description") or error.get("error")
            if isinstance(description, str):
                detail += f": {description}"
        except (ValueError, TypeError):
            pass
        raise AuthenticationError(f"The identity provider rejected the login: {detail}")

    try:
        id_token, refresh_token = _parse_token_response(response.json())
    except (ValueError, KeyError, TypeError) as e:
        raise AuthenticationError(
            "The identity provider did not return both an ID token and a refresh"
            f" token. Ensure the client allows offline access. ({e})"
        ) from None

    return TokenSet(
        id_token=id_token,
        refresh_token=refresh_token,
        token_endpoint=token_endpoint,
        client_id=client_id,
    )


def _secure_url(value: object, *, name: str, allow_query: bool = True) -> str:
    """Validates an OAuth endpoint, allowing HTTP only for local development."""
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")

    parsed = urllib.parse.urlsplit(value)
    is_loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if not parsed.netloc or parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and not is_loopback:
        raise ValueError(f"{name} must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError(f"{name} must not include credentials or a fragment")
    if not allow_query and parsed.query:
        raise ValueError(f"{name} must not include a query")
    return value
