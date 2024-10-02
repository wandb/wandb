"""apikey util."""

import os
import platform
import stat
import sys
import textwrap
from functools import partial
from typing import TYPE_CHECKING, Callable, Dict, Optional, Union
from urllib.parse import urlparse

# import Literal
if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

import click
from requests.utils import NETRC_FILES, get_netrc_auth

import wandb
from wandb.apis import InternalApi
from wandb.errors import term
from wandb.util import _is_databricks, isatty, prompt_choices

from .wburls import wburls

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

Mode = Literal["allow", "must", "never", "false", "true"]

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


getpass = partial(click.prompt, hide_input=True, err=True)


def _fixup_anon_mode(default: Optional[Mode]) -> Optional[Mode]:
    # Convert weird anonymode values from legacy settings files
    # into one of our expected values.
    anon_mode = default or "never"
    mapping: Dict[Mode, Mode] = {"true": "allow", "false": "never"}
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


def prompt_api_key(  # noqa: C901
    settings: "Settings",
    api: Optional[InternalApi] = None,
    input_callback: Optional[Callable] = None,
    browser_callback: Optional[Callable] = None,
    no_offline: bool = False,
    no_create: bool = False,
    local: bool = False,
) -> Union[str, bool, None]:
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
            write_key(settings, key, api=api)
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

    api_ask = (
        f"{log_string}: Paste an API key from your profile and hit enter, "
        "or press ctrl+c to quit"
    )
    if result == LOGIN_CHOICE_ANON:
        key = api.create_anonymous_api_key()

        write_key(settings, key, api=api, anonymous=True)
        return key  # type: ignore
    elif result == LOGIN_CHOICE_NEW:
        key = browser_callback(signup=True) if browser_callback else None

        if not key:
            wandb.termlog(f"Create an account here: {app_url}/authorize?signup=true")
            key = input_callback(api_ask).strip()

        write_key(settings, key, api=api)
        return key  # type: ignore
    elif result == LOGIN_CHOICE_EXISTS:
        key = browser_callback() if browser_callback else None

        if not key:
            if not (settings.is_local or local):
                host = app_url
                for prefix in ("http://", "https://"):
                    if app_url.startswith(prefix):
                        host = app_url[len(prefix) :]
                wandb.termlog(
                    f"Logging into {host}. (Learn how to deploy a W&B server locally: {wburls.get('wandb_server')})"
                )
            wandb.termlog(
                f"You can find your API key in your browser here: {app_url}/authorize"
            )
            key = input_callback(api_ask).strip()
        write_key(settings, key, api=api)
        return key  # type: ignore
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

        write_key(settings, key, api=api)
        return key  # type: ignore


def write_netrc(host: str, entity: str, key: str) -> Optional[bool]:
    """Add our host and key to .netrc."""
    _, key_suffix = key.split("-", 1) if "-" in key else ("", key)
    if len(key_suffix) != 40:
        wandb.termerror(
            "API-key must be exactly 40 characters long: {} ({} chars)".format(
                key_suffix, len(key_suffix)
            )
        )
        return None
    try:
        normalized_host = urlparse(host).netloc.split(":")[0]
        netrc_path = get_netrc_file_path()
        wandb.termlog(
            f"Appending key for {normalized_host} to your netrc file: {netrc_path}"
        )
        machine_line = f"machine {normalized_host}"
        orig_lines = None
        try:
            with open(netrc_path) as f:
                orig_lines = f.read().strip().split("\n")
        except OSError:
            pass
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
                        f.write("{}\n".format(line))
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
        return True
    except OSError:
        wandb.termerror(f"Unable to read {netrc_path}")
        return None


def write_key(
    settings: "Settings",
    key: Optional[str],
    api: Optional["InternalApi"] = None,
    anonymous: bool = False,
) -> None:
    if not key:
        raise ValueError("No API key specified.")

    # TODO(jhr): api shouldn't be optional or it shouldn't be passed, clean up callers
    api = api or InternalApi()

    # Normal API keys are 40-character hex strings. On-prem API keys have a
    # variable-length prefix, a dash, then the 40-char string.
    _, suffix = key.split("-", 1) if "-" in key else ("", key)

    if len(suffix) != 40:
        raise ValueError(
            "API key must be 40 characters long, yours was {}".format(len(key))
        )

    if anonymous:
        api.set_setting("anonymous", "true", globally=True, persist=True)
    else:
        api.clear_setting("anonymous", globally=True, persist=True)

    write_netrc(settings.base_url, "user", key)


def api_key(settings: Optional["Settings"] = None) -> Optional[str]:
    if settings is None:
        settings = wandb.setup().settings  # type: ignore
        assert settings is not None
    if settings.api_key:
        return settings.api_key
    auth = get_netrc_auth(settings.base_url)
    if auth:
        return auth[-1]
    return None
