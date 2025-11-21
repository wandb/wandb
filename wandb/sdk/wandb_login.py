"""Log in to Weights & Biases.

This authenticates your machine to log data to your account.
"""

from __future__ import annotations

import os

import click

import wandb
from wandb.errors import AuthenticationError, term
from wandb.old.settings import Settings as OldSettings
from wandb.sdk import wandb_setup
from wandb.sdk.lib import auth as wbauth
from wandb.sdk.lib.deprecation import UNSET, DoNotSet

from ..apis import InternalApi


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
        referrer=referrer or "models",
    )
    return logged_in


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
    _silent: bool | None = None,
) -> tuple[bool, str | None]:
    """Log in to W&B.

    Arguments are the same as for wandb.login() with the following additions:

    Args:
        update_api_key: If true and an explicit API key is given, it will be
            saved to the .netrc file.
        _silent: If true, will not print any messages to the console.

    Returns:
        A pair (is_successful, key).
    """
    settings = wandb_setup.singleton().settings

    if host is not None:
        settings.base_url = host
    if force is not None:
        settings.force = force
    if _silent:
        settings.silent = True

    if wandb.util._is_kaggle() and not wandb.util._has_internet():
        term.termerror(
            "To use W&B in kaggle you must enable internet in the settings"
            + " panel on the right."
        )
        return False, None

    if settings.identity_token_file:
        return True, None

    if not key:
        return _find_or_prompt_for_key(
            settings,
            relogin=relogin,
            verify=verify,
            referrer=referrer,
            input_timeout=timeout,
        )

    _use_explicit_key(
        key,
        settings=settings,
        verify=verify,
        update_api_key=update_api_key,
    )
    return True, key


def _use_explicit_key(
    key: str,
    settings: wandb.Settings,
    *,
    verify: bool,
    update_api_key: bool,
) -> None:
    """Log in with an explicit key.

    Same arguments as `_login()`.
    """
    if settings._notebook and not settings.silent:
        term.termwarn(
            "If you're specifying your api key in code, ensure this"
            + " code is not shared publicly."
            + "\nConsider setting the WANDB_API_KEY environment variable,"
            + " or running `wandb login` from the command line."
        )

    auth = wbauth.AuthApiKey(host=settings.base_url, api_key=key)

    if verify:
        _verify_login(auth.api_key, base_url=auth.host.url)

    wbauth.use_explicit_auth(auth, source="wandb.login()")

    if update_api_key:
        try:
            wbauth.write_netrc_auth(
                host=auth.host.url,
                api_key=auth.api_key,
            )
        except wbauth.WriteNetrcError as e:
            wandb.termwarn(str(e))

    if not settings._offline:
        wandb_setup.singleton().update_user_settings()

    if not settings.silent:
        _print_logged_in_message(settings)


def _find_or_prompt_for_key(
    settings: wandb.Settings,
    *,
    relogin: bool,
    verify: bool,
    referrer: str,
    input_timeout: float | None,
):
    """Log in without an explicit key.

    Same arguments as `_login()`.
    """
    timed_out = False
    auth: wbauth.Auth | None = None

    try:
        auth = wbauth.authenticate_session(
            host=settings.base_url,
            source="wandb.login()",
            no_offline=settings.force,
            no_create=settings.force,
            referrer=referrer,
            input_timeout=input_timeout,
            relogin=relogin,
        )

    except TimeoutError:
        timed_out = True

    if not auth:
        if timed_out:
            term.termwarn("W&B disabled due to login timeout.")
            settings.mode = "disabled"
        else:
            term.termlog("Using W&B in offline mode.")
            settings.mode = "offline"

        return False, None

    if not isinstance(auth, wbauth.AuthApiKey):
        raise NotImplementedError(str(auth))

    if verify:
        _verify_login(auth.api_key, base_url=auth.host.url)

    if not settings.silent:
        _print_logged_in_message(settings)

    return True, auth.api_key


def _verify_login(key: str, base_url: str) -> None:
    from requests.exceptions import ConnectionError

    api = InternalApi(
        api_key=key,
        default_settings={"base_url": base_url},
    )

    try:
        is_api_key_valid = api.validate_api_key()
    except ConnectionError:
        raise AuthenticationError(
            "Unable to connect to server to verify API token."
        ) from None
    except Exception as e:
        raise AuthenticationError(
            "An error occurred while verifying the API key."
        ) from e

    if not is_api_key_valid:
        raise AuthenticationError(
            f"API key verification failed for host {base_url}."
            + " Make sure your API key is valid."
        )


def _print_logged_in_message(settings: wandb.Settings) -> None:
    """Print a message telling the user they are logged in."""
    singleton = wandb_setup.singleton()
    username = singleton._get_username()

    if username:
        host_str = (
            f" to {click.style(settings.base_url, fg='green')}"
            if settings.base_url
            else ""
        )

        # check to see if we got an entity from the setup call or from the user
        entity = settings.entity or singleton._get_entity()

        entity_str = ""
        # check if entity exist, valid (is part of a certain team) and different from the username
        if entity and entity in singleton._get_teams() and entity != username:
            entity_str = f" ({click.style(entity, fg='yellow')})"

        login_state_str = f"Currently logged in as: {click.style(username, fg='yellow')}{entity_str}{host_str}"
    else:
        login_state_str = "W&B API key is configured"

    login_info_str = (
        f"Use {click.style('`wandb login --relogin`', bold=True)} to force relogin"
    )
    term.termlog(
        f"{login_state_str}. {login_info_str}",
        repeat=False,
    )
