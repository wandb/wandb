from __future__ import annotations

import netrc
import os
import pathlib
import platform
import shlex
from urllib.parse import urlsplit

from wandb.errors import term

from .auth import AuthApiKey, AuthWithSource
from .host_url import HostUrl


class WriteNetrcError(Exception):
    """Could not write to the netrc file."""


def read_netrc_auth(*, host: str | HostUrl) -> str | None:
    """Read a W&B API key from the .netrc file.

    Args:
        host: The W&B server URL.

    Returns:
        An API key for the host, or None if there's no .netrc file
        or if it doesn't contain credentials for the specified host.

    Raises:
        AuthenticationError: If an API key is found but is not in
            a valid format.
    """
    if not isinstance(host, HostUrl):
        host = HostUrl(host)

    if not (auth := read_netrc_auth_with_source(host=host)):
        return None

    assert isinstance(auth.auth, AuthApiKey)
    return auth.auth.api_key


def read_netrc_auth_with_source(*, host: HostUrl) -> AuthWithSource | None:
    """Read a W&B API key from the .netrc file.

    Args:
        host: The W&B server URL.

    Returns:
        An API key for the host, or None if there's no .netrc file
        or it doesn't contain credentials for the specified host.
        Also returns the file in which the API key was found.

    Raises:
        AuthenticationError: If an API key is found but is not in
            a valid format.
    """
    path = _get_netrc_file_path()

    try:
        netrc_file = netrc.netrc(path)
    except FileNotFoundError:
        return None
    except (netrc.NetrcParseError, OSError) as e:
        if isinstance(e, netrc.NetrcParseError) and e.lineno is not None:
            term.termwarn(
                f"Failed to read netrc file at {path},"
                + f" error on line {e.lineno}: {e.msg}"
            )
        else:
            term.termwarn(f"Failed to read netrc file at {path}: {e}")

        return None

    if not (netloc := urlsplit(host.url).netloc):
        return None
    if not (creds := netrc_file.authenticators(netloc)):
        return None

    _, _, password = creds
    if not password:
        term.termwarn(f"Found entry for machine {netloc!r} with no API key at {path}")
        return None

    return AuthWithSource(
        auth=AuthApiKey(host=host, api_key=password),
        source=str(path),
    )


def write_netrc_auth(*, host: str, api_key: str) -> None:
    """Store an API key in the .netrc file.

    Args:
        host: The W&B server URL.
        api_key: A valid API key to write.

    Raises:
        WriteNetrcError: If there's a problem writing to the .netrc file.
    """
    if not (netloc := urlsplit(host).netloc):
        raise ValueError(f"Invalid host URL: {host!r}")

    _update_netrc(
        _get_netrc_file_path(),
        machine=netloc,
        password=api_key,
    )


def _update_netrc(
    path: pathlib.Path,
    *,
    machine: str,
    password: str,
) -> None:
    # Avoid accidentally breaking the user's .netrc file
    # given invalid or malicious input.
    #
    # The .netrc file format allows using quotes in the same way
    # as in sh syntax; the built-in netrc library also uses shlex.
    quoted_machine = shlex.quote(machine)
    quoted_password = shlex.quote(password)

    orig_lines = []
    try:
        orig_lines = path.read_text().splitlines()
    except FileNotFoundError:
        term.termlog("No netrc file found, creating one.")
        path.touch(mode=0o600)  # user readable and writable
    except OSError as e:
        # Include the original error message because the stack trace
        # will not be shown to the user.
        raise WriteNetrcError(f"Unable to read {path}: {e}") from e

    new_lines: list[str] = []

    # Copy over the original lines, minus the machine section we're updating.
    in_old_entry = False
    for line in orig_lines:
        tokens = _split_netrc_line(line)

        if tokens[:2] == ["machine", machine]:
            in_old_entry = True
        elif tokens and tokens[0] in ("machine", "default"):
            in_old_entry = False

        if not in_old_entry:
            new_lines.append(line)

    new_lines.extend(
        [
            f"machine {quoted_machine}",
            "  login user",
            f"  password {quoted_password}",
            "",  # End with a blank line, by convention.
        ]
    )

    term.termlog(f"Appending key for {machine} to your netrc file: {path}")
    try:
        _write_text(path, "\n".join(new_lines))
    except OSError as e:
        # Include the original error message because the stack trace
        # will not be shown to the user.
        raise WriteNetrcError(f"Unable to write {path}: {e}") from e


def _split_netrc_line(line: str) -> list[str]:
    """Returns the .netrc tokens in a line.

    Falls back to splitting on whitespace if the line uses quotes incorrectly,
    since a malformed file must not prevent writing an API key.
    """
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def _write_text(path: pathlib.Path, text: str) -> None:
    """Call pathlib.Path.write_text().

    Patched in tests.
    """
    path.write_text(text)


def _get_netrc_file_path() -> pathlib.Path:
    """Returns the path to the .netrc file.

    The file at the path may or may not exist.
    """
    # The environment variable takes priority.
    if netrc_file := os.environ.get("NETRC"):
        return pathlib.Path(netrc_file).expanduser()

    # If a netrc file exists in a standard location, use it.
    unix_netrc = pathlib.Path("~/.netrc").expanduser()
    if unix_netrc.exists():
        return unix_netrc
    windows_netrc = pathlib.Path("~/_netrc").expanduser()
    if windows_netrc.exists():
        return windows_netrc

    # Otherwise, use the conventional file based on the platform.
    if platform.system() != "Windows":
        return unix_netrc
    else:
        return windows_netrc
