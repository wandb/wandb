"""Browser login: authorization code with PKCE, on a loopback redirect.

W&B is the authorization server. The browser session is the proof of identity,
so SAML, OIDC, and password logins work the same way.

Tokens go to the credentials file. wandb-core refreshes them. This module does
not, so a refresh token is never rotated from two places.
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
from collections.abc import Iterator
from typing import Any

import requests

from wandb.errors import AuthenticationError, term

from .host_url import HostUrl

CLI_CLIENT_ID = "wandb-cli"
"""Public OAuth client id. PKCE proves the request, not this string."""

CALLBACK_PATH = "/callback"
"""Loopback redirect path. The port is ephemeral; the path is fixed."""

_SUCCESS_PATH = "/cli-login-success"
"""App page shown after the loopback server receives the code."""

_CANCELLED_PATH = "/cli-login-cancelled"
"""App page shown when the user denies the login."""

LOGIN_TIMEOUT_SECONDS = 300.0
"""How long to wait for the browser. Covers SSO and MFA."""

_EXPIRES_AT_FORMAT = "%Y-%m-%d %H:%M:%S"
"""Credentials-file timestamp. wandb-core parses this as UTC."""


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
    client_id: str = CLI_CLIENT_ID,
    timeout: float = LOGIN_TIMEOUT_SECONDS,
    verify: bool | str = True,
) -> TokenSet:
    """Run a browser login and return the tokens it produced.

    Raises:
        AuthenticationError: The login was denied or the response was malformed.
        TimeoutError: The browser did not come back in time.
    """
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    with _callback_server(host) as server:
        redirect_uri = f"http://127.0.0.1:{server.server_port}{CALLBACK_PATH}"
        authorize_url = _authorize_url(
            host,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            challenge=challenge,
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
    """Revoke a refresh token (RFC 7009), which ends the login.

    Raises:
        AuthenticationError: The server refused. An unknown token is success,
            so a logout can be retried.
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
    """Whether a browser on this machine can complete the loopback redirect."""
    # Lazy import to avoid a circular import through wandb.sdk.lib.
    from wandb import util
    from wandb.sdk.lib import ipython

    if os.getenv("SSH_CONNECTION") or os.getenv("SSH_TTY"):
        return False

    if ipython.in_jupyter() or util._is_databricks():
        return False

    # Non-interactive processes, including most of CI, should not wait.
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return False

    # webbrowser can pick a terminal browser the user cannot act on.
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
        # Unreadable timestamp counts as expired. The refresh token still works.
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
    with _credentials_lock(path):
        credentials = _read_credentials(path)
        credentials[host.url] = tokens.to_json()
        _write_credentials(path, credentials)


def clear_credentials(
    credentials_file: str | pathlib.Path,
    host: HostUrl,
) -> TokenSet | None:
    """Remove the stored login for a host and return what was removed."""
    path = pathlib.Path(credentials_file)
    with _credentials_lock(path):
        existing = load_credentials(path, host)
        credentials = _read_credentials(path)
        if credentials.pop(host.url, None) is not None:
            _write_credentials(path, credentials)
        return existing


@contextlib.contextmanager
def _credentials_lock(path: pathlib.Path) -> Iterator[None]:
    """Exclusive lock on ``<credentials file>.lock``.

    wandb-core locks that same file around a refresh. Failing to lock is not
    fatal there, and it is not fatal here.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        yield
        return

    try:
        try:
            _lock_fd(fd)
        except OSError:
            yield
            return
        try:
            yield
        finally:
            _unlock_fd(fd)
    finally:
        os.close(fd)


def _lock_fd(fd: int) -> None:
    if sys.platform == "win32":
        _win_lock(fd, exclusive=True)
        return
    import fcntl

    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except InterruptedError:
            continue
        else:
            return


def _unlock_fd(fd: int) -> None:
    if sys.platform == "win32":
        _win_lock(fd, exclusive=False)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


def _win_lock(fd: int, *, exclusive: bool) -> None:
    """LockFileEx / UnlockFileEx, the same calls wandb-core uses on Windows."""
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = msvcrt.get_osfhandle(fd)
    # Zeroed OVERLAPPED: lock the file from offset 0. Kept alive for the call.
    overlapped = (ctypes.c_char * 32)()
    if exclusive:
        kernel32.LockFileEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        kernel32.LockFileEx.restype = ctypes.c_int
        # LOCKFILE_EXCLUSIVE_LOCK, whole file. Blocks until the lock is free.
        ok = kernel32.LockFileEx(
            handle, 0x2, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlapped)
        )
    else:
        kernel32.UnlockFileEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        kernel32.UnlockFileEx.restype = ctypes.c_int
        ok = kernel32.UnlockFileEx(
            handle, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlapped)
        )
    if not ok:
        raise OSError(ctypes.get_last_error())


def _read_credentials(path: pathlib.Path) -> dict[str, dict[str, str]]:
    """Read the credentials file. Missing or unreadable contents are empty."""
    try:
        contents = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}

    if not isinstance(contents, dict):
        return {}
    credentials = contents.get("credentials")
    if not isinstance(credentials, dict):
        return {}

    return {
        host: entry for host, entry in credentials.items() if isinstance(entry, dict)
    }


def _write_credentials(
    path: pathlib.Path,
    credentials: dict[str, dict[str, str]],
) -> None:
    """Replace the credentials file atomically.

    A partial write would drop a refresh token that nothing can recover.
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
    state: str,
    challenge: str,
) -> str:
    """Consent-page URL. The page posts the authorization request itself."""
    query = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

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

        self.send_response(302)
        self.send_header("Location", redirect_url)
        # The query string is an OAuth response.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default logging to stderr."""


@contextlib.contextmanager
def _callback_server(host: HostUrl) -> Iterator[http.server.HTTPServer]:
    """Loopback redirect on an ephemeral port. Bound to 127.0.0.1 only."""
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
    """Block until the redirect arrives. A request to another path does not end the wait."""
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
    """Pull the authorization code out of the redirect."""
    if error := _first(params, "error"):
        description = _first(params, "error_description")
        raise AuthenticationError(f"Login was not completed: {description or error}")

    state = _first(params, "state")
    # A mismatched state means this redirect is not from the login we started.
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
    """Trade the authorization code for tokens. The verifier binds it to this login."""
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
    """The server's error_description, or the HTTP status."""
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        detail = body.get("error_description") or body.get("error")
        if isinstance(detail, str) and detail:
            return detail

    return f"HTTP {response.status_code}"
