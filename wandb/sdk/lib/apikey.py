"""apikey util."""

from __future__ import annotations

import dataclasses
import os
import platform
import stat
import textwrap
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import wandb
from wandb.apis import InternalApi
from wandb.sdk import wandb_setup
from wandb.sdk.lib import auth

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


@dataclasses.dataclass(frozen=True)
class _NetrcPermissions:
    exists: bool
    read_access: bool
    write_access: bool


class WriteNetrcError(Exception):
    """Raised when we cannot write to the netrc file."""


def get_netrc_file_path() -> str:
    """Return the path to the netrc file."""
    from requests.utils import NETRC_FILES

    netrc_file = os.environ.get("NETRC")
    if netrc_file:
        return os.path.expanduser(netrc_file)

    # if either .netrc or _netrc exists in the home directory, use that
    for netrc_file in NETRC_FILES:
        home_dir = os.path.expanduser("~")
        if os.path.exists(os.path.join(home_dir, netrc_file)):
            return os.path.join(home_dir, netrc_file)

    # otherwise, use .netrc on non-Windows platforms and _netrc on Windows
    netrc_file = ".netrc" if platform.system() != "Windows" else "_netrc"

    return os.path.join(os.path.expanduser("~"), netrc_file)


def check_netrc_access(
    netrc_path: str,
) -> _NetrcPermissions:
    """Check if we can read and write to the netrc file."""
    file_exists = False
    write_access = False
    read_access = False
    try:
        st = os.stat(netrc_path)
        file_exists = True
        write_access = bool(st.st_mode & stat.S_IWUSR)
        read_access = bool(st.st_mode & stat.S_IRUSR)
    except FileNotFoundError:
        # If the netrc file doesn't exist, we will create it.
        write_access = True
        read_access = True
    except OSError as e:
        wandb.termerror(f"Unable to read permissions for {netrc_path}, {e}")

    return _NetrcPermissions(
        exists=file_exists,
        write_access=write_access,
        read_access=read_access,
    )


def write_netrc(host: str, entity: str, key: str):
    """Add our host and key to .netrc."""
    _, key_suffix = key.split("-", 1) if "-" in key else ("", key)
    if len(key_suffix) < 40:
        raise ValueError(
            f"API-key must be at least 40 characters long: {key_suffix} ({len(key_suffix)} chars)"
        )

    normalized_host = urlparse(host).netloc
    netrc_path = get_netrc_file_path()
    netrc_access = check_netrc_access(netrc_path)

    if not netrc_access.write_access or not netrc_access.read_access:
        raise WriteNetrcError(
            f"Cannot access {netrc_path}. In order to persist your API key, "
            "grant read and write permissions for your user to the file "
            'or specify a different file with the environment variable "NETRC=<new_netrc_path>".'
        )

    machine_line = f"machine {normalized_host}"
    orig_lines = None
    try:
        with open(netrc_path) as f:
            orig_lines = f.read().strip().split("\n")
    except FileNotFoundError:
        wandb.termlog("No netrc file found, creating one.")
    except OSError as e:
        raise WriteNetrcError(f"Unable to read {netrc_path}") from e

    try:
        with open(netrc_path, "w") as f:
            if orig_lines:
                # delete this machine from the file if it's already there.
                skip = 0
                for line in orig_lines:
                    # we fix invalid netrc files with an empty host that we wrote before
                    # verifying host...
                    if line == "machine " or machine_line in line:
                        skip = 2
                    elif skip:
                        skip -= 1
                    else:
                        f.write(f"{line}\n")

            wandb.termlog(
                f"Appending key for {normalized_host} to your netrc file: {netrc_path}"
            )
            f.write(
                textwrap.dedent(
                    """\
                    machine {host}
                      login {entity}
                      password {key}
                    """
                ).format(host=normalized_host, entity=entity, key=key)
            )
        os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as e:
        raise WriteNetrcError(f"Unable to write {netrc_path}") from e


def write_key(
    settings: Settings,
    key: str | None,
    api: InternalApi | None = None,
) -> None:
    if not key:
        raise ValueError("No API key specified.")

    if problems := auth.check_api_key(key):
        raise ValueError(problems)

    write_netrc(settings.base_url, "user", key)


def api_key(settings: Settings | None = None) -> str | None:
    from requests.utils import get_netrc_auth

    if settings is None:
        settings = wandb_setup.singleton().settings
    if settings.api_key:
        return settings.api_key

    netrc_access = check_netrc_access(get_netrc_file_path())
    if netrc_access.exists and not netrc_access.read_access:
        wandb.termwarn(f"Cannot access {get_netrc_file_path()}.")
        return None

    if netrc_access.exists:
        auth = get_netrc_auth(settings.base_url)
        if auth:
            return auth[-1]

    return None
