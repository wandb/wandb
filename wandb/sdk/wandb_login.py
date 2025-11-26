"""Log in to Weights & Biases.

This authenticates your machine to log data to your account.
"""

from __future__ import annotations

import enum
import os

import click

import wandb
from wandb.errors import AuthenticationError, UsageError, term
from wandb.old.settings import Settings as OldSettings
from wandb.sdk import wandb_setup
from wandb.sdk.lib import auth
from wandb.sdk.lib.deprecation import UNSET, DoNotSet

from ..apis import InternalApi


class OidcError(Exception):
    """OIDC is configured but not allowed."""


def _handle_host_wandb_setting(host: str | None, cloud: bool = False) -> None:
    """Write the host parameter to the global settings file.

    This takes the parameter from wandb.login or wandb login for use by the
    application's APIs.
    """
    _api = InternalApi()
    if host == "https://api.wandb.ai" or (host is None and cloud):
        _api.clear_setting("base_url", globally=True, persist=True)
        # To avoid writing an empty local settings file, we only clear if it exists
        if os.path.exists(OldSettings._local_path()):
            _api.clear_setting("base_url", persist=True)
    elif host:
        host = host.rstrip("/")
        # force relogin if host is specified
        _api.set_setting("base_url", host, globally=True, persist=True)


def _clear_anonymous_setting() -> None:
    """Delete the 'anonymous' setting from the global settings file.

    This setting is being removed, and this helps users remove it from their
    settings file by using `wandb login`. We do it here because `wandb login`
    used to automatically write the anonymous setting.
    """
    api = InternalApi()
    api.clear_setting("anonymous", globally=True, persist=True)


def login(
    key: str | None = None,
    relogin: bool | None = None,
    host: str | None = None,
    force: bool | None = None,
    timeout: int | None = None,
    verify: bool = False,
    referrer: str | None = None,
    anonymous: DoNotSet = UNSET,
) -> bool:
    """Log into W&B.

    You generally don't have to use this because most W&B methods that need
    authentication can log in implicitly. This is the programmatic counterpart
    to the `wandb login` CLI.

    This updates global credentials for the session (affecting all wandb usage
    in the current Python process after this call) and possibly the .netrc file.

    If the identity_token_file setting is set, like through the
    WANDB_IDENTITY_TOKEN_FILE environment variable, then this is a no-op.

    Otherwise, if an explicit API key is provided, it is used and written to
    the system .netrc file. If no key is provided, but the session is already
    authenticated, then the session key is used for verification (if verify
    is True) and the .netrc file is not updated.

    If none of the above is true, then this gets the API key from the first of:

    - The WANDB_API_KEY environment variable
    - The api_key setting in a system or workspace settings file
    - The .netrc file (either ~/.netrc, ~/_netrc or the path specified by the
      NETRC environment variable)
    - An interactive prompt (if available)

    Args:
        key: The API key to use.
        relogin: If true, get the API key from an interactive prompt, skipping
            reading .netrc, environment variables, etc.
        host: The W&B server URL to connect to.
        force: If true, disallows selecting offline mode in the interactive
            prompt.
        timeout: Number of seconds to wait for user input in the interactive
            prompt. This can be used as a failsafe if an interactive prompt
            is incorrectly shown in a non-interactive environment.
        verify: Verify the credentials with the W&B server and raise an
            AuthenticationError on failure.
        referrer: The referrer to use in the URL login request for analytics.

    Returns:
        bool: If `key` is configured.

    Raises:
        AuthenticationError: If `api_key` fails verification with the server.
        UsageError: If `api_key` cannot be configured and no tty.
    """
    if anonymous is not UNSET:
        term.termwarn(
            "The anonymous parameter to wandb.login() has no effect and will"
            + " be removed in future versions.",
            repeat=False,
        )

    if wandb.run is not None:
        term.termwarn("Calling wandb.login() after wandb.init() has no effect.")
        return False

    global_settings = wandb_setup.singleton().settings
    if global_settings._noop:
        return False
    if global_settings._offline and not global_settings.x_cli_only_mode:
        term.termwarn("Unable to verify login in offline mode.")
        return False

    _handle_host_wandb_setting(host)
    _clear_anonymous_setting()

    logged_in, _ = _login(
        key=key,
        relogin=relogin,
        host=host,
        force=force,
        timeout=timeout,
        verify=verify,
        referrer=referrer,
    )
    return logged_in


class ApiKeyStatus(enum.Enum):
    VALID = 1
    NOTTY = 2
    OFFLINE = 3
    DISABLED = 4


class _WandbLogin:
    def __init__(
        self,
        force: bool | None = None,
        host: str | None = None,
        key: str | None = None,
        relogin: bool | None = None,
        timeout: int | None = None,
    ):
        self._relogin = relogin

        login_settings = {
            "api_key": key,
            "base_url": host,
            "force": force,
            "login_timeout": timeout,
        }

        self._wandb_setup = wandb_setup.singleton()
        self._wandb_setup.settings.update_from_dict(login_settings)
        self._settings = self._wandb_setup.settings

    def _print_logged_in_message(self) -> None:
        """Prints a message telling the user they are logged in."""
        username = self._wandb_setup._get_username()

        if username:
            host_str = (
                f" to {click.style(self._settings.base_url, fg='green')}"
                if self._settings.base_url
                else ""
            )

            # check to see if we got an entity from the setup call or from the user
            entity = self._settings.entity or self._wandb_setup._get_entity()

            entity_str = ""
            # check if entity exist, valid (is part of a certain team) and different from the username
            if (
                entity
                and entity in self._wandb_setup._get_teams()
                and entity != username
            ):
                entity_str = f" ({click.style(entity, fg='yellow')})"

            login_state_str = f"Currently logged in as: {click.style(username, fg='yellow')}{entity_str}{host_str}"
        else:
            login_state_str = "W&B API key is configured"

        login_info_str = (
            f"Use {click.style('`wandb login --relogin`', bold=True)} to force relogin"
        )
        wandb.termlog(
            f"{login_state_str}. {login_info_str}",
            repeat=False,
        )

    def try_save_api_key(self, key: str) -> None:
        """Saves the API key to disk for future use."""
        if self._settings._notebook and not self._settings.silent:
            wandb.termwarn(
                "If you're specifying your api key in code, ensure this"
                + " code is not shared publicly."
                + "\nConsider setting the WANDB_API_KEY environment variable,"
                + " or running `wandb login` from the command line."
            )

        try:
            auth.write_netrc_auth(host=self._settings.base_url, api_key=key)
        except auth.WriteNetrcError as e:
            wandb.termwarn(str(e))

    def update_session(
        self,
        key: str | None,
        status: ApiKeyStatus = ApiKeyStatus.VALID,
    ) -> None:
        """Updates mode and API key settings on the global setup object.

        If we're online, this also pulls in user settings from the server.
        """
        login_settings = dict()
        if status == ApiKeyStatus.OFFLINE:
            login_settings = dict(mode="offline")
        elif status == ApiKeyStatus.DISABLED:
            login_settings = dict(mode="disabled")
        elif key:
            login_settings = dict(api_key=key)
        self._wandb_setup.settings.update_from_dict(login_settings)
        # Whenever the key changes, make sure to pull in user settings
        # from server.
        if not self._wandb_setup.settings._offline:
            self._wandb_setup.update_user_settings()

    def prompt_api_key(self, referrer: str) -> tuple[str | None, ApiKeyStatus]:
        """Prompt the user for an API key.

        Returns:
            (key, VALID) if a key was provided.
            (None, OFFLINE) if the user selected offline mode.
            (None, DISABLED) if a timeout occurred.

        Raises:
            UsageError: If interactive prompting is unavailable.
        """
        try:
            key = auth.prompt_and_save_api_key(
                host=self._settings.base_url,
                no_offline=self._settings.force,
                no_create=self._settings.force,
                referrer=referrer,
                input_timeout=self._settings.login_timeout,
            )

        except TimeoutError:
            wandb.termlog("W&B disabled due to login timeout.")
            return None, ApiKeyStatus.DISABLED

        except term.NotATerminalError:
            message = "No API key configured. Use `wandb login` to log in."
            raise UsageError(message) from None

        if not key:
            return None, ApiKeyStatus.OFFLINE

        return key, ApiKeyStatus.VALID


def _login(
    *,
    key: str | None = None,
    relogin: bool | None = None,
    host: str | None = None,
    force: bool | None = None,
    timeout: int | None = None,
    verify: bool = False,
    referrer: str = "models",
    update_api_key: bool = True,
    no_oidc: bool = False,
    _silent: bool | None = None,
) -> tuple[bool, str | None]:
    """Logs in to W&B.

    This is the internal implementation of wandb.login(),
    with many of the same arguments as wandb.login().
    Additional arguments are documented below.

    Args:
        update_api_key: If true, the api key will be saved or updated
            in the users .netrc file.
        no_oidc: If true, raise an OidcError instead of returning early if OIDC
            credentials are configured.
        _silent: If true, will not print any messages to the console.

    Returns:
        bool: If the login was successful
            or the user is assumed to be already be logged in.
        str: The API key used to log in,
            or None if the api key was not verified during the login process.
    """
    wlogin = _WandbLogin(
        force=force,
        host=host,
        key=key,
        relogin=relogin,
        timeout=timeout,
    )

    if wandb.util._is_kaggle() and not wandb.util._has_internet():
        term.termerror(
            "To use W&B in kaggle you must enable internet in the settings"
            + " panel on the right."
        )
        return False, None

    if wlogin._settings.identity_token_file:
        if no_oidc:
            raise OidcError

        return True, None

    if key:
        if problems := auth.check_api_key(key):
            raise AuthenticationError(problems)

        if verify:
            _verify_login(key, wlogin._settings.base_url)

        if update_api_key:
            wlogin.try_save_api_key(key)

        wlogin.update_session(key, status=ApiKeyStatus.VALID)

        if not _silent:
            wlogin._print_logged_in_message()

        return True, key

    # See if there already is a key in settings. This is true if WANDB_API_KEY
    # was set or login() already happened.
    if not relogin and (settings_key := wlogin._settings.api_key):
        key = settings_key
        key_status = ApiKeyStatus.VALID

    # Otherwise, try the .netrc file.
    elif not relogin and (
        netrc_key := auth.read_netrc_auth(host=wlogin._settings.base_url)
    ):
        key = netrc_key
        key_status = ApiKeyStatus.VALID

    # Finally (or necessarily, if relogin was set), prompt interactively.
    else:
        key, key_status = wlogin.prompt_api_key(referrer=referrer)

    # The key may be None if offline mode was selected interactively.

    if key and verify:
        _verify_login(key, wlogin._settings.base_url)
    wlogin.update_session(key, status=key_status)
    if key and not _silent:
        wlogin._print_logged_in_message()

    return key is not None, key


def _verify_login(key: str, base_url: str) -> None:
    from requests.exceptions import ConnectionError

    api = InternalApi(
        api_key=key,
        default_settings={"base_url": base_url},
    )

    try:
        is_api_key_valid = api.validate_api_key()
    except ConnectionError as e:
        raise AuthenticationError(
            f"Unable to connect to {base_url} to verify API token."
        ) from e
    except Exception as e:
        raise AuthenticationError(
            "An error occurred while verifying the API key."
        ) from e

    if not is_api_key_valid:
        raise AuthenticationError(
            f"API key verification failed for host {base_url}."
            " Make sure your API key is valid."
        )
