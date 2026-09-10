"""Browser-based OIDC login for `wandb login sso`."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import http.server
import ipaddress
import json
import secrets
import time
import urllib.parse
import webbrowser
from collections.abc import Sequence

import requests

from wandb import env
from wandb.errors import AuthenticationError, term

from .host_url import HostUrl
from .identity_token_file import Account

_DEFAULT_SCOPES = ("openid", "profile", "email", "offline_access")
_LOGIN_TIMEOUT_SECONDS = 300.0

# The device flow gets longer than the PKCE flow because the user may be
# walking over to another device to approve it.
_DEVICE_LOGIN_TIMEOUT_SECONDS = 900.0
_DEVICE_POLL_INTERVAL_SECONDS = 5.0
_MIN_DEVICE_POLL_INTERVAL_SECONDS = 1.0
_DEVICE_SLOW_DOWN_INCREMENT_SECONDS = 5.0
_DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


@dataclasses.dataclass(frozen=True)
class IdpConfig:
    """IdP connection details returned by `GET /oidc/cli_config`."""

    issuer: str
    client_id: str
    scopes: tuple[str, ...]

    auth_methods: tuple[str, ...] | None = None
    """The login flows the W&B server says the client supports.

    None if the server did not say, in which case the CLI attempts whichever
    flow the user asked for and lets the IdP reject it.
    """


@dataclasses.dataclass(frozen=True)
class OidcDiscovery:
    """OIDC endpoints used by the login flows."""

    authorization_endpoint: str
    token_endpoint: str
    device_authorization_endpoint: str | None = None

    iss_parameter_supported: bool = False
    """Whether the IdP promises to identify itself in authorization responses.

    When true, a response without an `iss` parameter is rejected (RFC 9207
    section 2.4). When false the parameter is still checked if it arrives,
    since an IdP may send it without advertising it.
    """


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

    return IdpConfig(
        issuer=issuer,
        client_id=client_id,
        scopes=tuple(scopes),
        auth_methods=_parse_auth_methods(body),
    )


def _parse_auth_methods(body: dict) -> tuple[str, ...] | None:
    """Reads the advertised login flows, or None if the server omitted them."""
    methods = body.get("auth_methods")
    if methods is None:
        # Older servers advertised a single method under a singular key.
        if (method := body.get("auth_method")) is None:
            return None
        methods = [method]

    if (
        not isinstance(methods, (list, tuple))
        or not methods
        or not all(isinstance(method, str) and method for method in methods)
    ):
        raise TypeError("auth_methods must be a non-empty list of strings")

    return tuple(methods)


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
    # Only IdPs that enable the device grant publish this endpoint, so its
    # absence is not an error until a device-code login asks for it.
    device_endpoint = body.get("device_authorization_endpoint")
    if device_endpoint is not None:
        device_endpoint = _secure_url(
            device_endpoint, name="device_authorization_endpoint"
        )

    iss_supported = body.get("authorization_response_iss_parameter_supported", False)
    if not isinstance(iss_supported, bool):
        raise TypeError(
            "authorization_response_iss_parameter_supported must be a boolean"
        )

    return OidcDiscovery(
        authorization_endpoint=_secure_url(
            body["authorization_endpoint"], name="authorization_endpoint"
        ),
        token_endpoint=_secure_url(body["token_endpoint"], name="token_endpoint"),
        device_authorization_endpoint=device_endpoint,
        iss_parameter_supported=iss_supported,
    )


def fetch_idp_config(host: HostUrl, *, org: str | None = None) -> IdpConfig:
    """Fetches the host's CLI SSO configuration."""
    try:
        _secure_url(host.url, name="W&B host")
    except (TypeError, ValueError) as e:
        raise AuthenticationError(str(e)) from None
    url = f"{host.url}/oidc/cli_config"

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


def login_with_pkce(host: HostUrl, *, org: str | None = None) -> Account:
    """Runs discovery and an Authorization Code + PKCE login."""
    idp_config = fetch_idp_config(host, org=org)
    _check_auth_method(
        idp_config,
        "pkce",
        f"{host} does not offer browser login. Add --use-device-code to your command.",
    )

    discovery = discover_oidc(idp_config.issuer)
    return dataclasses.replace(
        pkce_login(
            idp_config,
            discovery,
            success_redirect_url=f"{host.url}/cli-login-success",
        ),
        host=host.url,
        org=org,
    )


def login_with_device_code(host: HostUrl, *, org: str | None = None) -> Account:
    """Runs discovery and a device authorization login."""
    idp_config = fetch_idp_config(host, org=org)
    _check_auth_method(
        idp_config,
        "device_code",
        f"{host} does not offer device code login. Remove --use-device-code"
        " and try again.",
    )

    discovery = discover_oidc(idp_config.issuer)
    return dataclasses.replace(
        device_code_login(idp_config, discovery),
        host=host.url,
        org=org,
    )


def _check_auth_method(idp_config: IdpConfig, method: str, message: str) -> None:
    """Fails early if the server says it does not offer a login flow."""
    if idp_config.auth_methods is not None and method not in idp_config.auth_methods:
        raise AuthenticationError(message)


def pkce_login(
    idp_config: IdpConfig,
    discovery: OidcDiscovery,
    *,
    timeout: float = _LOGIN_TIMEOUT_SECONDS,
    success_redirect_url: str | None = None,
) -> Account:
    """Performs an Authorization Code + PKCE login on a loopback server.

    If `success_redirect_url` is set, a successful callback redirects the
    browser there (the W&B app's CLI-login landing page); otherwise, and on
    error callbacks, a minimal inline notice page is served.
    """
    code_verifier, code_challenge = _new_pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)

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
            nonce=nonce,
            code_challenge=code_challenge,
        )

        if _try_open_browser(auth_url):
            term.termlog(f"Opened {auth_url} in your browser.")
        else:
            term.termlog(f"Open this URL to log in:\n{auth_url}")

        params = _wait_for_callback(server, timeout=timeout)
    finally:
        server.server_close()

    code = _authorization_code(
        params,
        expected_state=state,
        expected_issuer=idp_config.issuer,
        require_issuer=discovery.iss_parameter_supported,
    )

    return _exchange_code(
        discovery.token_endpoint,
        client_id=idp_config.client_id,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        nonce=nonce,
    )


def device_code_login(
    idp_config: IdpConfig,
    discovery: OidcDiscovery,
    *,
    timeout: float = _DEVICE_LOGIN_TIMEOUT_SECONDS,
) -> Account:
    """Performs a device authorization login, per RFC 8628.

    This prints the IdP's verification URL and user code, and opens the URL
    in a local browser if there is one. The flow works headless either way:
    it exists for machines with no browser at all, and for users who prefer
    to approve the login from a phone or another computer.
    """
    if not discovery.device_authorization_endpoint:
        raise AuthenticationError(
            f"The identity provider at {idp_config.issuer} does not support"
            " device code login. Ask a W&B admin to enable the device"
            " authorization grant on the CLI's OAuth client, or remove"
            " --use-device-code and try again."
        )

    # Keycloak (and possibly other IdPs) requires PKCE on the device
    # authorization request whenever the client has PKCE enforced, even
    # though RFC 8628 itself doesn't mention PKCE.
    code_verifier, code_challenge = _new_pkce_pair()

    authorization = _request_device_code(
        discovery.device_authorization_endpoint,
        client_id=idp_config.client_id,
        scopes=idp_config.scopes,
        code_challenge=code_challenge,
    )

    prefilled = authorization.verification_uri_complete
    url = prefilled or authorization.verification_uri

    term.termlog(
        (
            f"Opened {url} in your browser."
            if _try_open_browser(url)
            else f"Open this URL to log in:\n{url}"
        )
        + (
            f"\nIt should show the code {authorization.user_code}."
            if prefilled
            else f"\nThen enter the code {authorization.user_code}."
        )
    )

    return _poll_for_device_token(
        discovery.token_endpoint,
        client_id=idp_config.client_id,
        authorization=authorization,
        code_verifier=code_verifier,
        timeout=timeout,
    )


@dataclasses.dataclass(frozen=True)
class _DeviceAuthorization:
    """A device authorization response, per RFC 8628 section 3.2."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: float
    interval: float


def _parse_device_authorization(body: object) -> _DeviceAuthorization:
    if not isinstance(body, dict):
        raise TypeError("response must be an object")

    device_code = body["device_code"]
    user_code = body["user_code"]
    if not isinstance(device_code, str) or not device_code:
        raise TypeError("device_code must be a non-empty string")
    if not isinstance(user_code, str) or not user_code:
        raise TypeError("user_code must be a non-empty string")

    complete = body.get("verification_uri_complete")
    if complete is not None:
        complete = _secure_url(complete, name="verification_uri_complete")

    return _DeviceAuthorization(
        device_code=device_code,
        user_code=user_code,
        verification_uri=_secure_url(
            body["verification_uri"],
            name="verification_uri",
        ),
        verification_uri_complete=complete,
        expires_in=_seconds(
            body.get("expires_in"),
            name="expires_in",
            default=_DEVICE_LOGIN_TIMEOUT_SECONDS,
        ),
        # Floored so that an IdP reporting 0 doesn't turn the poll loop
        # into a hot loop against its own token endpoint.
        interval=max(
            _seconds(
                body.get("interval"),
                name="interval",
                default=_DEVICE_POLL_INTERVAL_SECONDS,
            ),
            _MIN_DEVICE_POLL_INTERVAL_SECONDS,
        ),
    )


def _seconds(value: object, *, name: str, default: float) -> float:
    """Reads an optional duration in seconds from a device-flow response."""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise TypeError(f"{name} must be a non-negative number")
    return float(value)


def _request_device_code(
    endpoint: str,
    *,
    client_id: str,
    scopes: Sequence[str],
    code_challenge: str,
) -> _DeviceAuthorization:
    """Requests a device code and user code (RFC 8628 section 3.1)."""
    try:
        response = requests.post(
            endpoint,
            data={
                "client_id": client_id,
                "scope": " ".join(scopes),
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
            timeout=env.get_http_timeout(10),
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise AuthenticationError(
            f"Failed to reach the identity provider at {endpoint}: {e}"
        ) from None

    if response.status_code != 200:
        raise AuthenticationError(
            "The identity provider rejected the device login request:"
            f" {_token_error_detail(response)}"
        )

    try:
        return _parse_device_authorization(response.json())
    except (ValueError, KeyError, TypeError) as e:
        raise AuthenticationError(
            f"{endpoint} returned an invalid device authorization response: {e}"
        ) from None


def _poll_for_device_token(
    token_endpoint: str,
    *,
    client_id: str,
    authorization: _DeviceAuthorization,
    code_verifier: str,
    timeout: float,
) -> Account:
    """Polls for the user's approval (RFC 8628 sections 3.4 and 3.5)."""
    interval = authorization.interval
    deadline = time.monotonic() + min(authorization.expires_in, timeout)

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AuthenticationError(
                "Timed out waiting for the SSO login to be approved. Run the"
                " command again to start over."
            )
        # Sleeping before the first poll avoids a request that is certain to
        # be pending, since the user has not opened the URL yet.
        time.sleep(min(interval, remaining))

        try:
            response = requests.post(
                token_endpoint,
                data={
                    "grant_type": _DEVICE_CODE_GRANT,
                    "client_id": client_id,
                    "device_code": authorization.device_code,
                    "code_verifier": code_verifier,
                },
                timeout=env.get_http_timeout(10),
                allow_redirects=False,
            )
        except requests.RequestException as e:
            raise AuthenticationError(
                f"Failed to reach the identity provider at {token_endpoint}: {e}"
            ) from None

        if response.status_code == 200:
            return _token_set(
                response,
                token_endpoint=token_endpoint,
                client_id=client_id,
            )

        error = _oauth_error_code(response)
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += _DEVICE_SLOW_DOWN_INCREMENT_SECONDS
            continue
        if error == "access_denied":
            raise AuthenticationError("SSO login failed: the request was denied.")
        if error == "expired_token":
            raise AuthenticationError(
                "SSO login failed: the code expired before the login was"
                " approved. Run the command again to start over."
            )
        raise AuthenticationError(
            f"The identity provider rejected the login: {_token_error_detail(response)}"
        )


def _try_open_browser(url: str) -> bool:
    """Tries to open a URL in a local browser."""
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


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
    nonce: str,
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
            "nonce": nonce,
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
            # The URL being redirected away from carries the authorization
            # code, so it must not travel to the W&B app as a referrer.
            self.send_header("Referrer-Policy", "no-referrer")
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


def _authorization_code(
    params: dict[str, list[str]],
    *,
    expected_state: str,
    expected_issuer: str | None = None,
    require_issuer: bool = False,
) -> str:
    """Extracts and validates the authorization code."""
    # Checked before the state and the issuer so that an IdP that rejects
    # the login says why, rather than being reported as a state mismatch:
    # RFC 6749 asks the IdP to echo the state on errors, but not every one
    # does, and an error response carries no code to be confused about.
    if error := params.get("error", [None])[0]:
        description = params.get("error_description", [error])[0]
        raise AuthenticationError(f"SSO login failed: {description}")

    if (state := params.get("state", [None])[0]) != expected_state:
        raise AuthenticationError(
            "SSO login failed: the redirect's state did not match the"
            " request. Please try again." + (f" (got {state!r})" if state else "")
        )

    if expected_issuer:
        _check_response_issuer(
            params,
            expected=expected_issuer,
            required=require_issuer,
        )

    if not (code := params.get("code", [None])[0]):
        raise AuthenticationError(
            "SSO login failed: the identity provider's redirect did not"
            " include an authorization code."
        )

    return code


def _check_response_issuer(
    params: dict[str, list[str]],
    *,
    expected: str,
    required: bool,
) -> None:
    """Rejects an authorization response from an unexpected IdP (RFC 9207).

    Every organization brings its own authorization server, so this client
    talks to many of them. Without this check, a code minted by one of them
    could be redeemed at another's token endpoint -- the mix-up attack the
    `iss` parameter exists to stop.
    """
    if (issuer := params.get("iss", [None])[0]) is None:
        if required:
            raise AuthenticationError(
                "SSO login failed: the identity provider says it identifies"
                " itself in authorization responses, but this one did not."
                " Please try again."
            )
        return

    if issuer.rstrip("/") != expected.rstrip("/"):
        raise AuthenticationError(
            f"SSO login failed: the redirect came from {issuer!r}, but the"
            f" login was sent to {expected!r}."
        )


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
    nonce: str,
) -> Account:
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
        raise AuthenticationError(
            f"The identity provider rejected the login: {_token_error_detail(response)}"
        )

    account = _token_set(response, token_endpoint=token_endpoint, client_id=client_id)
    _check_nonce(account.id_token, expected=nonce)
    return account


def _token_set(
    response: requests.Response,
    *,
    token_endpoint: str,
    client_id: str,
) -> Account:
    """Reads a successful token response into an account."""
    try:
        id_token, refresh_token = _parse_token_response(response.json())
    except (ValueError, KeyError, TypeError) as e:
        raise AuthenticationError(
            "The identity provider did not return both an ID token and a refresh"
            f" token. Ensure the client allows offline access. ({e})"
        ) from None

    return Account(
        id_token=id_token,
        refresh_token=refresh_token,
        token_endpoint=token_endpoint,
        client_id=client_id,
    )


def _check_nonce(id_token: str, *, expected: str) -> None:
    """Rejects an ID token minted for a different authorization request.

    Only a mismatch is an error. An IdP that omits the claim despite being
    sent a nonce is out of spec (OpenID Connect Core section 3.1.3.7) but
    common enough that failing the login over it would do more harm than
    the replay this guards against, which TLS to the token endpoint and
    the PKCE verifier already make impractical.
    """
    found = _jwt_claims(id_token).get("nonce")
    if found is not None and not secrets.compare_digest(
        str(found).encode(), expected.encode()
    ):
        raise AuthenticationError(
            "SSO login failed: the identity provider returned an ID token"
            " for a different login request. Please try again."
        )


def _jwt_claims(token: str) -> dict[str, object]:
    """Decodes a JWT's payload, with no signature verification.

    The token arrives over TLS from the token endpoint in response to this
    process's own code and verifier, so its authenticity comes from the
    transport; this only reads back what was asked for.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        payload = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(payload)
    except (ValueError, TypeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _oauth_error_code(response: requests.Response) -> str | None:
    """Returns the OAuth `error` code from a failed token response."""
    try:
        error = response.json().get("error")
    except (ValueError, TypeError, AttributeError):
        return None
    return error if isinstance(error, str) else None


def _token_error_detail(response: requests.Response) -> str:
    """Summarizes a failed OAuth token response for an error message."""
    detail = f"HTTP {response.status_code}"
    try:
        body = response.json()
        description = body.get("error_description") or body.get("error")
    except (ValueError, TypeError, AttributeError):
        return detail
    if isinstance(description, str):
        detail += f": {description}"
    return detail


def _secure_url(value: object, *, name: str, allow_query: bool = True) -> str:
    """Validates an OAuth endpoint, allowing HTTP only for local development."""
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")

    parsed = urllib.parse.urlsplit(value)
    if not parsed.netloc or parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and not _is_loopback(parsed.hostname):
        raise ValueError(f"{name} must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError(f"{name} must not include credentials or a fragment")
    if not allow_query and parsed.query:
        raise ValueError(f"{name} must not include a query")
    return value


def _is_loopback(hostname: str | None) -> bool:
    """Returns whether a URL's host never leaves this machine.

    This matches wandb-core's check, so that an endpoint the CLI accepts
    during local development is one wandb-core will accept too.
    """
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
