"""apikey util."""

from __future__ import annotations

import dataclasses
import os
import platform
import stat
import sys
import textwrap
from functools import partial

# import Literal
from typing import TYPE_CHECKING, Callable, Literal
from urllib.parse import urlparse

import click
from requests.utils import NETRC_FILES, get_netrc_auth

import wandb
from wandb.apis import InternalApi
from wandb.errors import term
from wandb.errors.links import url_registry
from wandb.sdk import wandb_setup
from wandb.util import _is_databricks, isatty, prompt_choices

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings

LOGIN_CHOICE_ANON = "Private W&B dashboard, no account required"
LOGIN_CHOICE_NEW = "Create a W&B account"
LOGIN_CHOICE_EXISTS = "Use an existing W&B account"
LOGIN_CHOICE_DRYRUN = "Don't visualize my results"
LOGIN_CHOICE_NOTTY = "Unconfigured"
LOGIN_CHOICES = [
    LOGIN_CHOICE_ANON,
    LOGIN_CHOICE_NEW,
    LOGIN_CHOICE_EXISTS,
    LOGIN_CHOICE_DRYRUN,
]


@dataclasses.dataclass(frozen=True)
class _NetrcPermissions:
    exists: bool
    read_access: bool
    write_access: bool


class WriteNetrcError(Exception):
    """Raised when we cannot write to the netrc file."""


Mode = Literal["allow", "must", "never", "false", "true"]


getpass = partial(click.prompt, hide_input=True, err=True)


def _fixup_anon_mode(default: Mode | None) -> Mode | None:
    # Convert weird anonymode values from legacy settings files
    # into one of our expected values.
    anon_mode = default or "never"
    mapping: dict[Mode, Mode] = {"true": "allow", "false": "never"}
    return mapping.get(anon_mode, anon_mode)


def get_netrc_file_path() -> str:
    """Return the path to the netrc file."""
    # if the NETRC environment variable is set, use that
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


def _api_key_prompt_str(app_url: str, referrer: str | None = None) -> str:
    """Generate a prompt string for API key authorization.

    Creates a URL string that directs users to the authorization page where they
    can find their API key.

    Args:
        app_url: The base URL of the W&B application.
        referrer: Optional referrer parameter to include in the URL.

    Returns:
        A formatted string with instructions and the authorization URL.
    """
    ref = ""
    if referrer:
        ref = f"?ref={referrer}"
    return f"You can find your API key in your browser here: {app_url}/authorize{ref}"


def prompt_api_key(  # noqa: C901
    settings: Settings,
    api: InternalApi | None = None,
    input_callback: Callable | None = None,
    browser_callback: Callable | None = None,
    no_offline: bool = False,
    no_create: bool = False,
    local: bool = False,
    referrer: str | None = None,
) -> str | bool | None:
    """Prompt for api key.

    Returns:
        str - if key is configured
        None - if dryrun is selected
        False - if unconfigured (notty)
    """
    input_callback = input_callback or getpass
    log_string = term.LOG_STRING
    api = api or InternalApi(settings)
    anon_mode = _fixup_anon_mode(settings.anonymous)  # type: ignore
    jupyter = settings._jupyter or False
    app_url = api.app_url

    choices = [choice for choice in LOGIN_CHOICES]
    if anon_mode == "never":
        # Omit LOGIN_CHOICE_ANON as a choice if the env var is set to never
        choices.remove(LOGIN_CHOICE_ANON)
    if (jupyter and not settings.login_timeout) or no_offline:
        choices.remove(LOGIN_CHOICE_DRYRUN)
    if (jupyter and not settings.login_timeout) or no_create:
        choices.remove(LOGIN_CHOICE_NEW)

    if jupyter and "google.colab" in sys.modules:
        log_string = term.LOG_STRING_NOCOLOR
        key = wandb.jupyter.attempt_colab_login(app_url)  # type: ignore
        if key is not None:
            return key  # type: ignore

    if anon_mode == "must":
        result = LOGIN_CHOICE_ANON
    # If we're not in an interactive environment, default to dry-run.
    elif (
        not jupyter and (not isatty(sys.stdout) or not isatty(sys.stdin))
    ) or _is_databricks():
        result = LOGIN_CHOICE_NOTTY
    elif local:
        result = LOGIN_CHOICE_EXISTS
    elif len(choices) == 1:
        result = choices[0]
    else:
        result = prompt_choices(
            choices, input_timeout=settings.login_timeout, jupyter=jupyter
        )

    key = None
    api_ask = (
        f"{log_string}: Paste an API key from your profile and hit enter"
        if jupyter
        else f"{log_string}: Paste an API key from your profile and hit enter, or press ctrl+c to quit"
    )
    if result == LOGIN_CHOICE_ANON:
        key = api.create_anonymous_api_key()
    elif result == LOGIN_CHOICE_NEW:
        key = browser_callback(signup=True) if browser_callback else None

        if not key:
            ref = f"&ref={referrer}" if referrer else ""
            wandb.termlog(
                f"Create an account here: {app_url}/authorize?signup=true{ref}"
            )
            key = input_callback(api_ask).strip()
    elif result == LOGIN_CHOICE_EXISTS:
        key = browser_callback() if browser_callback else None

        if not key:
            if not (settings.is_local or local):
                host = app_url
                for prefix in ("http://", "https://"):
                    if app_url.startswith(prefix):
                        host = app_url[len(prefix) :]
                wandb.termlog(
                    f"Logging into {host}. (Learn how to deploy a W&B server "
                    f"locally: {url_registry.url('wandb-server')})"
                )
            wandb.termlog(_api_key_prompt_str(app_url, referrer))
            key = input_callback(api_ask).strip()
    elif result == LOGIN_CHOICE_NOTTY:
        # TODO: Needs refactor as this needs to be handled by caller
        return False
    elif result == LOGIN_CHOICE_DRYRUN:
        return None
    else:
        # Jupyter environments don't have a tty, but we can still try logging in using
        # the browser callback if one is supplied.
        key, anonymous = (
            browser_callback() if jupyter and browser_callback else (None, False)
        )

    if not key:
        raise ValueError("No API key specified.")
    return key


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
    if len(key_suffix) != 40:
        raise ValueError(
            f"API-key must be exactly 40 characters long: {key_suffix} ({len(key_suffix)} chars)"
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

    # TODO(jhr): api shouldn't be optional or it shouldn't be passed, clean up callers
    api = api or InternalApi()

    # Normal API keys are 40-character hex strings. On-prem API keys have a
    # variable-length prefix, a dash, then the 40-char string.
    _, suffix = key.split("-", 1) if "-" in key else ("", key)

    if len(suffix) != 40:
        raise ValueError(f"API key must be 40 characters long, yours was {len(key)}")

    write_netrc(settings.base_url, "user", key)


def api_key(settings: Settings | None = None) -> str | None:
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
