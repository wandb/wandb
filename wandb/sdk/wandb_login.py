"""Log in to Weights & Biases.

This authenticates your machine to log data to your account.
"""

from __future__ import annotations

import os
import pathlib
from typing import TYPE_CHECKING

import click

import wandb
from wandb import env
from wandb.errors import AuthenticationError, UsageError, term
from wandb.sdk import wandb_setup
from wandb.sdk.lib import settings_file, urls, wbauth
from wandb.sdk.lib.deprecation import UNSET, DoNotSet
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi
    from wandb.sdk.lib.wbauth import browser_login


def login(
    key: str | None = None,
    relogin: bool | None = None,
    host: str | None = None,
    force: bool | None = None,
    timeout: int | None = None,
    verify: bool = True,
    referrer: str | None = None,
    prompt: bool = True,
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

    If none of the above is true, then this gets credentials from the first of:

    - The WANDB_API_KEY environment variable
    - A browser login stored by `wandb login --browser`
    - The .netrc file (either ~/.netrc, ~/_netrc or the path specified by the
      NETRC environment variable)
    - The api_key setting in a system or workspace settings file
    - An interactive prompt, if available and `prompt` is True

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
            AuthenticationError on failure. This works for API keys, browser
            logins, and identity tokens.
        referrer: The referrer to use in the URL login request for analytics.
        prompt: Whether to ask for an API key interactively when none is
            configured. If False, this returns False and leaves the session
            and settings unchanged.

    Returns:
        True if the session has credentials after this call.

    Raises:
        AuthenticationError: If the credentials fail verification with
            the server.
        UsageError: If no credentials are configured, `prompt` is True and
            there is no terminal to ask for an API key.
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
        host = wbauth.HostUrl(host).url

    logged_in, _ = _login(
        key=key,
        relogin=relogin,
        host=host,
        force=force,
        timeout=timeout,
        verify=verify,
        referrer=referrer or "models",
        prompt=prompt,
    )

    if not logged_in and not prompt:
        return False

    _update_system_settings(
        global_settings.read_system_settings(),
        host=host,
    )
    return logged_in


def _resolve_host(settings: wandb.Settings, host: str | None) -> wbauth.HostUrl:
    if host is None:
        return wbauth.HostUrl(settings.base_url, app_url=settings.app_url)
    return wbauth.HostUrl(host)


def _update_system_settings(
    system_settings: settings_file.SettingsFiles,
    *,
    host: str | None,
) -> None:
    """Update the user's system settings files."""
    # 'anonymous' is deprecated; we clear it automatically for now.
    system_settings.clear("anonymous", globally=True)

    if host:
        if host == urls.DEFAULT_BASE_URL:
            system_settings.clear("base_url", globally=True)
        else:
            system_settings.set("base_url", host, globally=True)

    try:
        system_settings.save()
    except settings_file.SaveSettingsError as e:
        wandb.termwarn(str(e))


def _login_with_browser(
    *,
    host: str | None = None,
    relogin: bool = False,
    verify: bool = True,
) -> None:
    """Log in through the browser, or reuse the browser login already stored.

    There is one browser login per host. It is reused unless `relogin` is set
    or it no longer verifies; a login this replaces is revoked.
    """
    # Deferred to keep requests out of SDK and CLI startup.
    from wandb.sdk.lib.wbauth import browser_login

    settings = wandb_setup.singleton().settings
    host_url = _resolve_host(settings, host)
    persist_host = host_url.url if host else None
    credentials_file = pathlib.Path(settings.credentials_file)

    if not relogin and (
        auth := _reuse_browser_login(credentials_file, host_url, verify=verify)
    ):
        _finish_browser_login(settings, auth, persist_host=persist_host, reused=True)
        return

    if not browser_login.can_open_browser():
        raise UsageError(
            "`wandb login --browser` needs a browser on this machine to"
            " finish the login. Run it where you have one, or log in with"
            " an API key instead."
        )

    auth, previous = _acquire_browser_login(
        credentials_file=credentials_file,
        host_url=host_url,
        verify=verify,
        insecure_disable_ssl=settings.insecure_disable_ssl,
    )
    _finish_browser_login(settings, auth, persist_host=persist_host, reused=False)

    if previous is not None:
        wbauth.revoke_browser_login(
            host=host_url,
            refresh_token=previous.refresh_token,
        )


def _reuse_browser_login(
    credentials_file: pathlib.Path,
    host_url: wbauth.HostUrl,
    *,
    verify: bool,
) -> wbauth.AuthBrowserLogin | None:
    """Return the stored browser login if it is present and still verifies."""
    from wandb.sdk.lib.wbauth import browser_login

    if not browser_login.load_credentials(credentials_file, host_url):
        return None

    auth = wbauth.AuthBrowserLogin(
        host=host_url,
        credentials_file=credentials_file,
    )
    if not verify:
        return auth

    try:
        auth.verify()
    except AuthenticationError as e:
        term.termwarn(
            f"Could not use the browser login stored for {host_url}"
            f" ({e}). Logging in again."
        )
        return None

    return auth


def _acquire_browser_login(
    *,
    credentials_file: pathlib.Path,
    host_url: wbauth.HostUrl,
    verify: bool,
    insecure_disable_ssl: bool,
) -> tuple[wbauth.AuthBrowserLogin, browser_login.TokenSet | None]:
    """Run the browser flow, store the login, and verify it.

    The previous login stays on disk until this one is stored and accepted.
    A failure, including Ctrl-C, puts that previous login back. Any failure
    other than Ctrl-C also revokes the new login (using the rotated refresh
    token if verification refreshed it).
    """
    from wandb.sdk.lib.wbauth import browser_login

    tokens = browser_login.login(
        host=host_url,
        timeout=browser_login.LOGIN_TIMEOUT_SECONDS,
        verify=not insecure_disable_ssl,
    )
    try:
        previous = browser_login.save_credentials(credentials_file, host_url, tokens)
    except AuthenticationError:
        wbauth.revoke_browser_login(
            host=host_url,
            refresh_token=tokens.refresh_token,
            description="the new browser login",
        )
        raise

    auth = wbauth.AuthBrowserLogin(
        host=host_url,
        credentials_file=credentials_file,
    )
    if verify:
        try:
            auth.verify()
        except BaseException as e:
            replaced = _restore_browser_credentials(
                credentials_file,
                host_url,
                previous,
            )
            # Ctrl-C should exit right away, not wait on the server.
            if isinstance(e, Exception):
                wbauth.revoke_browser_login(
                    host=host_url,
                    refresh_token=(replaced or tokens).refresh_token,
                    description="the new browser login",
                )
            raise

    return auth, previous


def _restore_browser_credentials(
    credentials_file: pathlib.Path,
    host_url: wbauth.HostUrl,
    previous: browser_login.TokenSet | None,
) -> browser_login.TokenSet | None:
    """Put the previous login back (or remove the new one) after a failed verify."""
    from wandb.sdk.lib.wbauth import browser_login

    try:
        if previous is None:
            return browser_login.clear_credentials(credentials_file, host_url)
        return browser_login.save_credentials(credentials_file, host_url, previous)
    except AuthenticationError as e:
        term.termwarn(f"Could not restore credentials for {host_url}: {e}")
        return None


def _finish_browser_login(
    settings: wandb.Settings,
    auth: wbauth.AuthBrowserLogin,
    *,
    persist_host: str | None,
    reused: bool,
) -> None:
    """Activate session auth, persist host settings, and report login status."""
    wbauth.use_explicit_auth(auth, source="wandb login")
    wandb_setup.singleton().update_user_settings()
    _update_system_settings(
        settings.read_system_settings(),
        host=persist_host,
    )
    if not settings.silent:
        _print_logged_in_message(
            settings,
            host=str(auth.host),
            auth=auth,
            reused=reused,
        )
    _warn_if_env_overrides_browser_login()


def _warn_if_env_overrides_browser_login() -> None:
    """Warn when an exported credential will be used instead of the browser login."""
    for var in (env.API_KEY, env.IDENTITY_TOKEN_FILE):
        if os.getenv(var):
            term.termwarn(
                f"{var} is set, so W&B uses it instead of the browser login."
                f" Unset {var} to use the browser login."
            )
            return


def _login(
    *,
    key: str | None = None,
    relogin: bool | None = None,
    host: str | None = None,
    force: bool | None = None,
    timeout: float | None = None,
    verify: bool = False,
    referrer: str = "models",
    prompt: bool = True,
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
    host_url = _resolve_host(settings, host)

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
            prompt=prompt,
        )

    wandb_setup.singleton().update_user_settings()
    if auth is not None and not _silent:
        _print_logged_in_message(settings, host=str(host_url), auth=auth)

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
        else:
            # A browser login outranks .netrc, so it would hide the saved API key.
            wbauth.clear_browser_login(host=auth.host)

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
    prompt: bool,
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
            prompt=prompt,
        )

    except TimeoutError:
        timed_out = True

    if not auth and prompt:
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

    The verification request is made by wandb-core, which supports API keys,
    identity token files (federated identity), and browser logins.

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
    from wandb.apis.public.service_api import ServiceApi

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


def _format_identity_summary(settings: wandb.Settings, *, host: str) -> str | None:
    """Format `<username> (<entity>) to <host>` if the viewer can be resolved."""
    singleton = wandb_setup.singleton()
    username = singleton._get_username()
    if not username:
        return None

    host_str = f" to {click.style(host, fg='green')}" if host else ""

    # Check to see if we got an entity from the setup call or from the user.
    entity = settings.entity or singleton._get_entity()

    entity_str = ""
    # Check if entity exists, is valid (part of a team), and differs from username.
    if entity and entity in singleton._get_teams() and entity != username:
        entity_str = f" ({click.style(entity, fg='yellow')})"

    return f"{click.style(username, fg='yellow')}{entity_str}{host_str}"


def _format_logged_in_state(
    settings: wandb.Settings,
    *,
    host: str,
    auth: wbauth.Auth | None,
    reused: bool,
) -> str:
    """Format the account or credential summary for the logged-in message."""
    if identity := _format_identity_summary(settings, host=host):
        if reused:
            return f"Already logged in as: {identity} through the browser"
        return f"Currently logged in as: {identity}"

    if isinstance(auth, wbauth.AuthBrowserLogin):
        host_str = f" to {click.style(host, fg='green')}" if host else ""
        prefix = "Already logged in" if reused else "Logged in"
        return f"{prefix}{host_str} through the browser"

    if isinstance(auth, wbauth.AuthIdentityTokenFile):
        return "W&B credentials are configured"

    return "W&B API key is configured"


def _print_logged_in_message(
    settings: wandb.Settings,
    *,
    host: str,
    auth: wbauth.Auth | None = None,
    reused: bool = False,
) -> None:
    """Print a message telling the user they are logged in."""
    login_state_str = _format_logged_in_state(
        settings,
        host=host,
        auth=auth,
        reused=reused,
    )
    relogin_cmd = (
        "`wandb login --browser --relogin`"
        if isinstance(auth, wbauth.AuthBrowserLogin)
        else "`wandb login --relogin`"
    )
    login_info_str = f"Use {click.style(relogin_cmd, bold=True)} to force relogin"
    term.termlog(
        f"{login_state_str}. {login_info_str}",
        repeat=False,
    )
