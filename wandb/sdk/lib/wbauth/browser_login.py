"""Browser-based login against the W&B authorization server.

W&B is the authorization server here, not the customer's identity provider. The
proof of who you are is the session you already have in your browser, so an
organization using SAML, OIDC, or plain passwords all work the same way and no
per-organization application registration is needed.

The flow is the Authorization Code grant with PKCE (RFC 7636) on a loopback
redirect (RFC 8252):

1. The CLI starts an HTTP server on an ephemeral loopback port.
2. It opens `/cli-login` in the browser, which asks the user to approve and to
   pick which organization the token should be scoped to.
3. The server redirects back to the loopback port with an authorization code.
4. The CLI exchanges the code, plus the PKCE verifier, for an access token and
   a refresh token.

The tokens are written to the credentials file, where wandb-core picks them up
and refreshes them as they expire. Nothing here refreshes: doing it in one place
is what keeps rotation from tripping the server's reuse detection.
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import datetime
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import sys
import tempfile
import time
import urllib.parse
import webbrowser
from collections.abc import Iterator, Sequence
from typing import Any

import requests

from wandb.errors import AuthenticationError, term

from .host_url import HostUrl

CLI_CLIENT_ID = "wandb-cli"
"""The public OAuth client the CLI identifies itself as.

Public means it holds no secret. What proves a token request belongs to the
browser login that started it is PKCE, not this string.
"""

CALLBACK_PATH = "/callback"
"""Path of the loopback redirect.

The server registers `http://127.0.0.1/callback` and matches the port loosely
per RFC 8252 section 7.3, so the port may be ephemeral but the path may not
vary.
"""

_SUCCESS_PATH = "/cli-login-success"
"""Where the browser lands once the loopback server has the code.

Points at a W&B page instead of rendering HTML from this process, so what the
user sees at the end of `wandb login sso` looks like the rest of the product.
This page does not need the viewer's W&B session: the login it is reporting
on is the CLI's, not this browser tab's.
"""

_CANCELLED_PATH = "/cli-login-cancelled"
"""Where the browser lands when the user denies CLI login."""

DEFAULT_SCOPES = (
    "runs.read",
    "runs.write",
    "artifacts.read",
    "artifacts.write",
)

LOGIN_TIMEOUT_SECONDS = 300.0
"""How long to wait for the browser half of the login.

Long enough to sign in to an identity provider and work through a multi-factor
prompt, short enough that a forgotten terminal does not hold a port forever.
"""

_EXPIRES_AT_FORMAT = "%Y-%m-%d %H:%M:%S"
"""Timestamp format in the credentials file.

This has to match the layout wandb-core parses, in
`core/internal/api/credentials.go`. It has no timezone, and core treats it as
UTC, so times written here must be UTC too.
"""


@dataclasses.dataclass(frozen=True)
class TokenSet:
    """An access token and the refresh token that replaces it."""

    access_token: str
    refresh_token: str
    expires_at: datetime.datetime

    def to_json(self) -> dict[str, str]:
        return {
            "expires_at": self.expires_at.strftime(_EXPIRES_AT_FORMAT),
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
        }


def login(
    *,
    host: HostUrl,
    organization: str | None = None,
    client_id: str = CLI_CLIENT_ID,
    scopes: Sequence[str] = DEFAULT_SCOPES,
    timeout: float = LOGIN_TIMEOUT_SECONDS,
    verify: bool | str = True,
) -> TokenSet:
    """Run a browser login and return the tokens it produced.

    Args:
        host: The W&B server to log in to.
        organization: Scope the token to this organization. When omitted, the
            consent page asks the user to choose from the organizations they
            belong to.
        client_id: The OAuth client to identify as. Deployments that registered
            their own may override it.
        scopes: The scopes to request.
        timeout: Seconds to wait for the browser to come back.
        verify: TLS verification for the token exchange, as requests takes it:
            False to skip it, or a path to a CA bundle.

    Raises:
        AuthenticationError: If the login is denied or the response is
            malformed.
        TimeoutError: If the browser does not come back in time.
    """
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    with _callback_server(host) as server:
        redirect_uri = f"http://127.0.0.1:{server.server_port}{CALLBACK_PATH}"
        authorize_url = _authorize_url(
            host,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            state=state,
            challenge=challenge,
            organization=organization,
        )

        if _open_browser(authorize_url):
            term.termlog(f"Opened {authorize_url} in your browser.")
        else:
            term.termlog(f"Open this URL to log in:\n{authorize_url}")

        params = _wait_for_callback(server, timeout=timeout)

    code = _authorization_code(params, expected_state=state)

    return _exchange_code(
        host,
        client_id=client_id,
        code=code,
        redirect_uri=redirect_uri,
        verifier=verifier,
        verify=verify,
    )


def revoke(
    *,
    host: HostUrl,
    refresh_token: str,
    client_id: str = CLI_CLIENT_ID,
    timeout: float = 30.0,
    verify: bool | str = True,
) -> None:
    """Revoke a login at the server (RFC 7009).

    Revoking the refresh token ends the whole login, including the access
    tokens issued from it, so a logged-out credential cannot be used even if a
    copy of it was taken.

    Raises:
        AuthenticationError: If the server refuses the revocation. An unknown
            token is not a refusal; RFC 7009 has the server treat that as
            success so a client can retry a logout.
    """
    response = requests.post(
        f"{host.url}/oidc/revoke",
        data={
            "client_id": client_id,
            "token": refresh_token,
            "token_type_hint": "refresh_token",
        },
        timeout=timeout,
        verify=verify,
    )
    if not response.ok:
        raise AuthenticationError(
            f"Failed to log out of {host}: {_error_detail(response)}"
        )


def can_open_browser() -> bool:
    """Returns whether this process can run the browser half of a login.

    Two things have to be true, and the second is the one that catches people
    out: a browser has to exist, and it has to be running on the same machine as
    this process, because the authorization code comes back to a loopback port
    here. A remote shell or a notebook kernel usually satisfies the first and
    not the second, and it fails by hanging until the login times out rather
    than by erroring, so those are ruled out up front.
    """
    # Lazy import to avoid a circular import through wandb.sdk.lib.
    from wandb import util
    from wandb.sdk.lib import ipython

    if os.getenv("SSH_CONNECTION") or os.getenv("SSH_TTY"):
        return False

    if ipython.in_jupyter() or util._is_databricks():
        return False

    # A login nobody is watching should not be waiting on a browser. This also
    # covers piped and redirected invocations, which is most of CI.
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return False

    # webbrowser falls back to terminal browsers, which can "succeed" at
    # opening a URL the user cannot act on, so a graphical session is required
    # where that is a meaningful distinction.
    if sys.platform not in ("darwin", "win32") and not (
        os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")
    ):
        return False

    try:
        webbrowser.get()
    except webbrowser.Error:
        return False

    return True


def load_credentials(
    credentials_file: str | pathlib.Path,
    host: HostUrl,
) -> TokenSet | None:
    """Return the browser login stored for a host, if there is one."""
    entry = _read_credentials(pathlib.Path(credentials_file)).get(host.url)
    if not entry or not entry.get("refresh_token"):
        return None

    try:
        expires_at = datetime.datetime.strptime(
            entry.get("expires_at", ""), _EXPIRES_AT_FORMAT
        ).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        # Treat an unreadable timestamp as already expired rather than
        # discarding the tokens: the refresh token is what matters, and core
        # will mint a new access token from it.
        expires_at = datetime.datetime.now(datetime.timezone.utc)

    return TokenSet(
        access_token=entry.get("access_token", ""),
        refresh_token=entry["refresh_token"],
        expires_at=expires_at,
    )


def save_credentials(
    credentials_file: str | pathlib.Path,
    host: HostUrl,
    tokens: TokenSet,
) -> None:
    """Store a browser login, leaving logins for other hosts alone."""
    path = pathlib.Path(credentials_file)
    credentials = _read_credentials(path)
    credentials[host.url] = tokens.to_json()
    _write_credentials(path, credentials)


def clear_credentials(
    credentials_file: str | pathlib.Path,
    host: HostUrl,
) -> TokenSet | None:
    """Remove the stored login for a host and return what was removed."""
    path = pathlib.Path(credentials_file)
    existing = load_credentials(path, host)

    credentials = _read_credentials(path)
    if credentials.pop(host.url, None) is not None:
        _write_credentials(path, credentials)

    return existing


def _read_credentials(path: pathlib.Path) -> dict[str, dict[str, str]]:
    """Read the credentials file, treating anything unreadable as empty.

    A missing file is the normal state before the first login. A corrupt one is
    not worth failing over either, since the only thing to do about it is write
    a good one.
    """
    try:
        contents = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}

    credentials = contents.get("credentials") if isinstance(contents, dict) else None
    if not isinstance(credentials, dict):
        return {}

    return {
        host: entry for host, entry in credentials.items() if isinstance(entry, dict)
    }


def _write_credentials(
    path: pathlib.Path,
    credentials: dict[str, dict[str, str]],
) -> None:
    """Replace the credentials file.

    Written to a temporary file and renamed so that a reader, which may be
    wandb-core refreshing in another process, sees either the old file or the
    new one. A partial write would lose the refresh token, and nothing could
    recover it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    handle, temp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".credentials-",
        suffix=".json",
    )
    try:
        with os.fdopen(handle, "w") as file:
            json.dump({"credentials": credentials}, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise


def _pkce_pair() -> tuple[str, str]:
    """Return a (verifier, challenge) pair per RFC 7636 section 4."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _authorize_url(
    host: HostUrl,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    state: str,
    challenge: str,
    organization: str | None,
) -> str:
    """Build the URL of the consent page that starts the login.

    This points at the W&B app rather than at an OAuth endpoint. The page shows
    what is being granted and to which organization, and only then posts the
    authorization request to the server.
    """
    query = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if organization:
        query["organization"] = organization

    return f"{host.app_url}/cli-login?{urllib.parse.urlencode(query)}"


def _open_browser(url: str) -> bool:
    """Try to open a URL in a local browser."""
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Receive the authorization server's redirect."""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        callback_params = urllib.parse.parse_qs(parsed.query)
        self.server.callback_params = callback_params  # type: ignore[attr-defined]

        redirect_url = self.server.success_redirect_url  # type: ignore[attr-defined]
        if callback_params.get("error") == ["access_denied"]:
            redirect_url = self.server.cancelled_redirect_url  # type: ignore[attr-defined]

        # Hand the tab off to a W&B page rather than rendering local HTML.
        self.send_response(302)
        self.send_header("Location", redirect_url)
        # The callback carries an OAuth response, so keep it out of caches and
        # out of the referrer of anything it links to.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default logging to stderr."""


@contextlib.contextmanager
def _callback_server(host: HostUrl) -> Iterator[http.server.HTTPServer]:
    """Serve the loopback redirect on an ephemeral port.

    Bound to 127.0.0.1 rather than to every interface: the authorization code
    arrives in this request, and nothing outside this machine should be able to
    deliver or intercept one.
    """
    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.callback_params = None  # type: ignore[attr-defined]
    server.success_redirect_url = f"{host.app_url}{_SUCCESS_PATH}"  # type: ignore[attr-defined]
    server.cancelled_redirect_url = f"{host.app_url}{_CANCELLED_PATH}"  # type: ignore[attr-defined]
    try:
        yield server
    finally:
        server.server_close()


def _wait_for_callback(
    server: http.server.HTTPServer,
    *,
    timeout: float,
) -> dict[str, list[str]]:
    """Block until the redirect arrives, or the deadline passes.

    Requests are handled one at a time until one of them is the callback, so
    that a stray request to another path does not end the wait.
    """
    deadline = time.monotonic() + timeout

    while getattr(server, "callback_params", None) is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Timed out waiting for the login to complete in the browser."
            )
        server.timeout = remaining
        server.handle_request()

    return server.callback_params  # type: ignore[attr-defined]


def _authorization_code(
    params: dict[str, list[str]],
    *,
    expected_state: str,
) -> str:
    """Pull the authorization code out of the redirect.

    Raises:
        AuthenticationError: If the server reported an error, or the response
            does not match the request we started.
    """
    if error := _first(params, "error"):
        description = _first(params, "error_description")
        raise AuthenticationError(f"Login was not completed: {description or error}")

    state = _first(params, "state")
    # A redirect that does not carry back the state we generated did not come
    # from the login we started, so the code in it is not ours to redeem.
    if not state or not secrets.compare_digest(state, expected_state):
        raise AuthenticationError(
            "Login response did not match the request. Run `wandb login` again."
        )

    code = _first(params, "code")
    if not code:
        raise AuthenticationError(
            "Login response did not include an authorization code."
        )

    return code


def _exchange_code(
    host: HostUrl,
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
    verifier: str,
    timeout: float = 30.0,
    verify: bool | str = True,
) -> TokenSet:
    """Trade the authorization code for tokens.

    The verifier is what proves this exchange belongs to the browser login that
    produced the code. Without it a code intercepted from the redirect would be
    redeemable by anyone.
    """
    response = requests.post(
        f"{host.url}/oidc/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        timeout=timeout,
        verify=verify,
    )
    if not response.ok:
        raise AuthenticationError(
            f"Failed to complete login with {host}: {_error_detail(response)}"
        )

    try:
        body = response.json()
    except ValueError:
        raise AuthenticationError(
            f"{host} returned a token response that was not JSON."
        ) from None

    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    if not access_token or not refresh_token:
        raise AuthenticationError(f"{host} returned an incomplete token response.")

    expires_in = body.get("expires_in")
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=int(expires_in) if isinstance(expires_in, (int, float, str)) else 0
    )

    return TokenSet(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def _first(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    return values[0] if values else None


def _error_detail(response: requests.Response) -> str:
    """Describe a failed OAuth response using the server's own error fields."""
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        detail = body.get("error_description") or body.get("error")
        if isinstance(detail, str) and detail:
            return detail

    return f"HTTP {response.status_code}"
