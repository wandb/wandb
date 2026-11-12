"""Browser login: authorization code with PKCE on a loopback redirect.

Tokens are saved under ``user_credentials`` in the credentials file, apart from
the identity token exchanges wandb-core keeps under ``credentials``. Only
wandb-core refreshes them, so a refresh token is never rotated from two places.
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
from collections.abc import Callable, Generator
from typing import IO, Any, cast

import requests
from typing_extensions import final, override

from wandb import util
from wandb.errors import AuthenticationError, term
from wandb.sdk.lib import ipython

from .host_url import HostUrl

# Must match CLIClientID in wandb-core.
CLI_CLIENT_ID = "wandb-cli"
_CALLBACK_PATH = "/callback"

LOGIN_TIMEOUT_SECONDS = 300.0
_EXCHANGE_TIMEOUT_SECONDS = 30.0

_CONSENT_PATH = "/cli-login"
_SUCCESS_PATH = "/cli-login-success"
_CANCELLED_PATH = "/cli-login-cancelled"

_USER_CREDENTIALS_KEY = "user_credentials"

# wandb-core parses this as UTC.
_EXPIRES_AT_FORMAT = "%Y-%m-%d %H:%M:%S"


@final
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
    timeout: float = LOGIN_TIMEOUT_SECONDS,
    verify: bool | str = True,
) -> TokenSet:
    """Run a browser login.

    Args:
        host: The W&B server to log in to.
        timeout: How long to wait for the browser, in seconds.
        verify: Passed to `requests` to control TLS verification.

    Returns:
        The tokens issued for the login.

    Raises:
        AuthenticationError: If the login was denied or the server's
            response was malformed.
        TimeoutError: If the browser did not complete the login in time.
    """
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    def exchange(params: dict[str, list[str]]) -> TokenSet:
        return _exchange_code(
            host,
            code=_authorization_code(params),
            redirect_uri=server.redirect_uri,
            verifier=verifier,
            # The code has already been sent, so allow at least a moment.
            timeout=min(_EXCHANGE_TIMEOUT_SECONDS, max(server.remaining(), 1.0)),
            verify=verify,
        )

    with _CallbackServer(host, state, exchange) as server:
        authorize_url = _authorize_url(
            host,
            redirect_uri=server.redirect_uri,
            state=state,
            challenge=challenge,
        )

        if _open_browser(authorize_url):
            term.termlog(f"Opened {authorize_url} in your browser.")
        else:
            term.termlog(f"Open this URL to log in:\n{authorize_url}")

        return _wait_for_login(server, timeout=timeout)


def revoke(
    *,
    host: HostUrl,
    refresh_token: str,
    timeout: float = 30.0,
    verify: bool | str = True,
) -> None:
    """Revoke a refresh token (RFC 7009), which ends the login.

    Revoking an unknown token succeeds, so it can be retried.

    Args:
        host: The W&B server that issued the token.
        refresh_token: The refresh token to revoke.
        timeout: How long to wait for the server, in seconds.
        verify: Passed to `requests` to control TLS verification.

    Raises:
        AuthenticationError: If the server refused.
    """
    try:
        response = requests.post(
            f"{host.url}/oidc/revoke",
            data={
                "client_id": CLI_CLIENT_ID,
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
            timeout=timeout,
            verify=verify,
        )
    except requests.RequestException as e:
        raise AuthenticationError(f"Could not reach {host} to log out: {e}") from e

    if not response.ok:
        raise AuthenticationError(
            f"Failed to log out of {host}: {_error_detail(response)}"
        )


def can_open_browser() -> bool:
    """Returns whether a local browser can complete the loopback redirect."""
    if os.getenv("SSH_CONNECTION") or os.getenv("SSH_TTY"):
        return False

    if ipython.in_jupyter() or util._is_databricks():
        return False

    # Non-interactive processes, including most CI, should not wait.
    if not (_is_tty(sys.stdin) and _is_tty(sys.stderr)):
        return False

    # Without a display, webbrowser may pick a terminal browser.
    if sys.platform not in ("darwin", "win32") and not (
        os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")
    ):
        return False

    try:
        webbrowser.get()
    except webbrowser.Error:
        return False

    return True


def _is_tty(stream: IO[str] | None) -> bool:
    """Returns whether a standard stream is a terminal.

    A standard stream is None when the process has no console, as under
    pythonw, and isatty() raises if the stream has been closed.
    """
    if stream is None:
        return False

    try:
        return stream.isatty()
    except ValueError:
        return False


def load_credentials(
    credentials_file: pathlib.Path,
    host: HostUrl,
) -> TokenSet | None:
    """Returns the browser login stored for a host, if there is one.

    Args:
        credentials_file: The path to the credentials file.
        host: The W&B server the login is for.
    """
    contents = _read_file(credentials_file)
    entry = _user_credentials(contents).get(host.url)
    if not isinstance(entry, dict):
        return None

    refresh_token = entry.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return None

    # An unusable access token is replaced on the next refresh.
    access_token = entry.get("access_token")
    if not isinstance(access_token, str):
        access_token = ""

    try:
        expires_at = datetime.datetime.strptime(
            entry.get("expires_at", ""), _EXPIRES_AT_FORMAT
        ).replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        # Treat an unreadable timestamp as expired; the refresh token still works.
        expires_at = datetime.datetime.now(datetime.timezone.utc)

    return TokenSet(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def save_credentials(
    credentials_file: pathlib.Path,
    host: HostUrl,
    tokens: TokenSet,
) -> None:
    """Stores a browser login, leaving every other entry in the file alone.

    Args:
        credentials_file: The path to the credentials file.
        host: The W&B server the login is for.
        tokens: The tokens to store.
    """
    with _credentials_lock(credentials_file):
        contents = _read_file(credentials_file, strict=True)
        _user_credentials(contents)[host.url] = tokens.to_json()
        _write_file(credentials_file, contents)


def clear_credentials(
    credentials_file: pathlib.Path,
    host: HostUrl,
) -> TokenSet | None:
    """Removes the stored login for a host and returns what was removed.

    An identity token exchange for the same host is left in place.

    Args:
        credentials_file: The path to the credentials file.
        host: The W&B server the login is for.
    """
    with _credentials_lock(credentials_file):
        contents = _read_file(credentials_file, strict=True)
        existing = load_credentials(credentials_file, host)
        if _user_credentials(contents).pop(host.url, None) is not None:
            _write_file(credentials_file, contents)
        return existing


@contextlib.contextmanager
def _credentials_lock(path: pathlib.Path) -> Generator[None]:
    """Locks ``<credentials file>.lock``, which wandb-core also locks.

    Like wandb-core, proceeds without the lock if it cannot be taken.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path.with_name(f"{path.name}.lock"), os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        yield
        return

    with contextlib.ExitStack() as stack:
        stack.callback(os.close, fd)
        with contextlib.suppress(OSError):
            _lock_fd(fd)
            stack.callback(_unlock_fd, fd)
        yield


def _lock_fd(fd: int) -> None:
    if sys.platform == "win32":
        _win_lock(fd, exclusive=True)
        return

    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    if sys.platform == "win32":
        _win_lock(fd, exclusive=False)
        return

    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


def _win_lock(fd: int, *, exclusive: bool) -> None:
    """Calls LockFileEx or UnlockFileEx, as wandb-core does on Windows."""
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = msvcrt.get_osfhandle(fd)
    # A zeroed OVERLAPPED locks from offset 0.
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
        # LOCKFILE_EXCLUSIVE_LOCK over the whole file; blocks until available.
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


def _read_file(path: pathlib.Path, *, strict: bool = False) -> dict[str, Any]:
    """Reads the credentials file, keeping entries this module does not own.

    A missing file is treated as empty. So is an unreadable one, unless
    `strict` is set; callers that write the file back must set it so a bad
    read never replaces other logins with an empty file.

    Raises:
        AuthenticationError: If `strict` and the file exists but can't be
            read or parsed.
    """
    contents: Any = {}
    try:
        contents = json.loads(path.read_text())
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        if strict:
            raise AuthenticationError(
                f"Could not read the credentials file {path}: {e}"
            ) from e

    if not isinstance(contents, dict):
        if strict and contents is not None:
            raise AuthenticationError(
                f"The credentials file {path} is not a JSON object."
            )
        contents = {}

    # Older readers expect this map to be present.
    if not isinstance(contents.get("credentials"), dict):
        contents["credentials"] = {}
    return contents


def _user_credentials(contents: dict[str, Any]) -> dict[str, Any]:
    """Returns the user login map in the file contents, creating it if absent."""
    credentials = contents.get(_USER_CREDENTIALS_KEY)
    if not isinstance(credentials, dict):
        credentials = {}
        contents[_USER_CREDENTIALS_KEY] = credentials
    return credentials


def _write_file(path: pathlib.Path, contents: dict[str, Any]) -> None:
    """Replaces the credentials file atomically.

    A partial write would lose a refresh token that cannot be recovered.

    Raises:
        AuthenticationError: If the file can't be written.
    """
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=".credentials-",
            suffix=".json",
        )
        temp_path = pathlib.Path(temp_name)
        with os.fdopen(handle, "w") as file:
            json.dump(contents, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        temp_path.chmod(0o600)
        temp_path.replace(path)
    except OSError as e:
        raise AuthenticationError(
            f"Could not write the credentials file {path}: {e}"
        ) from e
    finally:
        # Gone already after a successful replace.
        if temp_path:
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)


def _pkce_pair() -> tuple[str, str]:
    """Returns a (verifier, challenge) pair per RFC 7636 section 4."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _page_url(host: HostUrl, path: str) -> str:
    """Returns the URL of a login page, which is at the root of the host."""
    parts = urllib.parse.urlsplit(host.app_url)
    return f"{parts.scheme}://{parts.netloc}{path}"


def _authorize_url(
    host: HostUrl,
    *,
    redirect_uri: str,
    state: str,
    challenge: str,
) -> str:
    """Returns the consent page URL, which posts the authorization request."""
    query = {
        "client_id": CLI_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

    return f"{_page_url(host, _CONSENT_PATH)}?{urllib.parse.urlencode(query)}"


def _open_browser(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Receives the authorization server's redirect."""

    # StreamRequestHandler.setup() makes this the socket timeout, so an idle
    # connection, like a browser preconnect, can't stall the login.
    timeout = 5.0

    @property
    def _login_server(self) -> _CallbackServer:
        return cast("_CallbackServer", self.server)

    @override
    def setup(self) -> None:
        super().setup()

        # One connection must not hold the server past the login's deadline.
        limit = self._login_server.remaining()
        if self.timeout is not None:
            limit = min(limit, self.timeout)
        # A timeout of zero would make the socket non-blocking instead.
        self.connection.settimeout(max(limit, 0.001))

    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        if url.path != _CALLBACK_PATH:
            self.send_error(404)
            return

        params = urllib.parse.parse_qs(url.query)
        server = self._login_server

        # Other requests to the loopback port must not end the login.
        state = _first(params, "state") or ""
        if not secrets.compare_digest(state.encode(), server.state.encode()):
            self.send_error(400)
            return

        # Reply after the exchange so a failed login never shows the success page.
        try:
            server.result = server.exchange(params)
        except Exception as e:
            server.result = e

        location = server.success_url
        if isinstance(server.result, Exception):
            location = server.cancelled_url

        self.send_response(302)
        self.send_header("Location", location)
        # The request URL carries an authorization code.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    @override
    def log_message(self, format: str, *args: Any) -> None:
        """Silences the default logging to stderr."""


class _CallbackServer(http.server.HTTPServer):
    """A server on an ephemeral loopback port that receives the redirect."""

    def __init__(
        self,
        host: HostUrl,
        state: str,
        exchange: Callable[[dict[str, list[str]]], TokenSet],
    ) -> None:
        super().__init__(("127.0.0.1", 0), _CallbackHandler)
        self.state = state
        self.exchange = exchange
        self.redirect_uri = f"http://127.0.0.1:{self.server_port}{_CALLBACK_PATH}"
        self.success_url = _page_url(host, _SUCCESS_PATH)
        self.cancelled_url = _page_url(host, _CANCELLED_PATH)

        # The tokens or the error, once the redirect has been handled.
        self.result: TokenSet | Exception | None = None

        # When the login gives up; set by _wait_for_login.
        self.deadline = float("inf")

    def remaining(self) -> float:
        """Returns the seconds left before the deadline."""
        return self.deadline - time.monotonic()


def _wait_for_login(server: _CallbackServer, *, timeout: float) -> TokenSet:
    """Blocks until a redirect with the expected state has been handled."""
    server.deadline = time.monotonic() + timeout

    while server.result is None:
        remaining = server.remaining()
        if remaining <= 0:
            raise TimeoutError(
                "Timed out waiting for the login to complete in the browser."
            )
        server.timeout = remaining
        server.handle_request()

    if isinstance(server.result, Exception):
        raise server.result
    return server.result


def _authorization_code(params: dict[str, list[str]]) -> str:
    if error := _first(params, "error"):
        description = _first(params, "error_description")
        raise AuthenticationError(f"Login was not completed: {description or error}")

    if not (code := _first(params, "code")):
        raise AuthenticationError(
            "Login response did not include an authorization code."
        )

    return code


def _exchange_code(
    host: HostUrl,
    *,
    code: str,
    redirect_uri: str,
    verifier: str,
    timeout: float = _EXCHANGE_TIMEOUT_SECONDS,
    verify: bool | str = True,
) -> TokenSet:
    try:
        response = requests.post(
            f"{host.url}/oidc/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLI_CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
            timeout=timeout,
            verify=verify,
        )
    except requests.RequestException as e:
        raise AuthenticationError(f"Could not reach {host} to log in: {e}") from e

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

    if not isinstance(body, dict):
        raise AuthenticationError(f"{host} returned an incomplete token response.")

    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    # wandb-core can't read a file with a non-string token, and drops all of it.
    if (
        not isinstance(access_token, str)
        or not isinstance(refresh_token, str)
        or not access_token
        or not refresh_token
    ):
        raise AuthenticationError(f"{host} returned an incomplete token response.")

    try:
        lifetime = datetime.timedelta(seconds=int(body.get("expires_in") or 0))
    except (TypeError, ValueError, OverflowError):
        # Treat an unreadable lifetime as already expired; wandb-core refreshes.
        lifetime = datetime.timedelta(0)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + lifetime

    return TokenSet(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def _first(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    return values[0] if values else None


def _error_detail(response: requests.Response) -> str:
    """Returns the server's error description, or the HTTP status."""
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        detail = body.get("error_description") or body.get("error")
        if isinstance(detail, str) and detail:
            return detail

    return f"HTTP {response.status_code}"
