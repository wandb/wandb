"""Log in to Weights & Biases.

This authenticates your machine to log data to your account.
"""

from __future__ import annotations

import click

import wandb
from wandb import env
from wandb.apis.public.service_api import ServiceApi
from wandb.errors import AuthenticationError, term
from wandb.sdk import wandb_setup
from wandb.sdk.lib import settings_file, wbauth
from wandb.sdk.lib.deprecation import UNSET, DoNotSet
from wandb.sdk.lib.service.service_connection import WandbApiFailedError


def login(
    key: str | None = None,
    relogin: bool | None = None,
    host: str | None = None,
    force: bool | None = None,
    timeout: int | None = None,
    verify: bool = True,
    referrer: str | None = None,
    anonymous: DoNotSet = UNSET,
) -> bool:
    """Log into W&B.

    You generally don't have to use this because most W&B methods that need
    authentication can log in implicitly. This is the programmatic counterpart
    to the `wandb login` CLI.

    This updates global credentials for the session (affecting all wandb usage
    in the current Python process after this call) and possibly the .netrc file.

    If an identity token file is configured, like through the
    WANDB_IDENTITY_TOKEN_FILE environment variable, then it is used for the
    session (federated identity) and no API key is read or saved.

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
            AuthenticationError on failure. This works for API keys as well
            as identity tokens.
        referrer: The referrer to use in the URL login request for analytics.

    Returns:
        bool: If `key` is configured.

    Raises:
        AuthenticationError: If the credentials fail verification with
            the server.
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

    if host:
        host = host.rstrip("/")

    logged_in, _ = _login(
        key=key,
        relogin=relogin,
        host=host,
        force=force,
        timeout=timeout,
        verify=verify,
        referrer=referrer or "models",
    )

    _update_system_settings(
        global_settings.read_system_settings(),
        host=host,
    )
    return logged_in


def _update_system_settings(
    system_settings: settings_file.SettingsFiles,
    *,
    host: str | None,
) -> None:
    """Update the user's system settings files."""
    # 'anonymous' is deprecated; we clear it automatically for now.
    system_settings.clear("anonymous", globally=True)

    if host:
        if host == "https://api.wandb.ai":
            system_settings.clear("base_url", globally=True)
        else:
            system_settings.set("base_url", host, globally=True)

    try:
        system_settings.save()
    except settings_file.SaveSettingsError as e:
        wandb.termwarn(str(e))


def _login(
    *,
    key: str | None = None,
    relogin: bool | None = None,
    host: str | None = None,
    force: bool | None = None,
    timeout: float | None = None,
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

    if host is None:
        host_url = wbauth.HostUrl(settings.base_url, app_url=settings.app_url)
    else:
        host_url = wbauth.HostUrl(host)

    if relogin is None:
        relogin = settings.relogin
    if force is None:
        force = settings.force
    if timeout is None:
        timeout = settings.login_timeout
    if _silent is None:
        _silent = settings.silent

    if wandb.util._is_kaggle() and not wandb.util._has_internet():
        term.termerror(
            "To use W&B in kaggle you must enable internet in the settings"
            + " panel on the right."
        )
        return False, None

    if key:
        auth: wbauth.Auth | None = _use_explicit_key(
            key,
            host=host_url,
            settings=settings,
            update_api_key=update_api_key,
            silent=_silent,
            verify=verify,
        )
    else:
        auth = _find_or_prompt_for_key(
            settings,
            host=host_url,
            force=force,
            relogin=relogin,
            referrer=referrer,
            input_timeout=timeout,
            verify=verify,
        )

    wandb_setup.singleton().update_user_settings()
    if not _silent:
        _print_logged_in_message(settings, host=str(host_url))

    if auth is None:
        return False, None
    elif isinstance(auth, wbauth.AuthApiKey):
        return True, auth.api_key
    else:
        return True, None


def _use_explicit_key(
    key: str,
    settings: wandb.Settings,
    *,
    host: wbauth.HostUrl,
    update_api_key: bool,
    silent: bool,
    verify: bool,
) -> wbauth.Auth:
    """Log in with an explicit key.

    Same arguments as `_login()`.
    """
    if settings._notebook and not silent:
        term.termwarn(
            "If you're specifying your api key in code, ensure this"
            + " code is not shared publicly."
            + "\nConsider setting the WANDB_API_KEY environment variable,"
            + " or running `wandb login` from the command line."
        )

    auth = wbauth.AuthApiKey(host=host, api_key=key)

    if verify:
        auth.verify()

    wbauth.use_explicit_auth(auth, source="wandb.login()")

    if update_api_key:
        try:
            wbauth.write_netrc_auth(
                host=auth.host.url,
                api_key=auth.api_key,
            )
        except wbauth.WriteNetrcError as e:
            wandb.termwarn(str(e))

    return auth


def _find_or_prompt_for_key(
    settings: wandb.Settings,
    *,
    host: wbauth.HostUrl,
    force: bool,
    relogin: bool,
    referrer: str,
    input_timeout: float | None,
    verify: bool,
) -> wbauth.Auth | None:
    """Log in without an explicit key.

    Same arguments as `_login()`.
    """
    timed_out = False
    auth: wbauth.Auth | None = None

    try:
        auth = wbauth.authenticate_session(
            host=host,
            source="wandb.login()",
            no_offline=force,
            no_create=force,
            referrer=referrer,
            input_timeout=input_timeout,
            relogin=relogin,
            verify=verify,
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

    return auth


def _verify_login(
    auth: wbauth.Auth,
    *,
    service_api: ServiceApi | None = None,
) -> None:
    """Check the credentials with the server they are for.

    The verification request is made by wandb-core, which supports both
    API keys and identity token files (federated identity).

    Args:
        auth: The credentials to verify.
        service_api: An existing service API handle configured with the
            given credentials to use for the request. If not given, a
            temporary one is created from the global settings and the
            credentials.

    Raises:
        AuthenticationError: If the server rejects the credentials or
            cannot be reached.
    """
    if service_api is None:
        settings = wandb_setup.singleton().settings.model_copy()
        wbauth.set_auth_settings(settings, auth)

        service_api = ServiceApi(
            settings=settings,
            timeout=env.get_http_timeout(10),
        )

    try:
        service_api.authenticate()
    except WandbApiFailedError as e:
        raise AuthenticationError(
            f"Failed to verify credentials with {auth.host}: {e}"
        ) from e
    except Exception as e:
        # Failures to start or connect to the wandb-core service process
        # are raised as various other exception types; keep this function's
        # contract of raising AuthenticationError for any failure.
        raise AuthenticationError(
            f"An error occurred while verifying credentials with {auth.host}: {e}"
        ) from e


def _print_logged_in_message(settings: wandb.Settings, *, host: str) -> None:
    """Print a message telling the user they are logged in."""
    singleton = wandb_setup.singleton()
    username = singleton._get_username()

    if username:
        host_str = f" to {click.style(host, fg='green')}" if host else ""

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
