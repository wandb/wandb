from __future__ import annotations

import os
import threading

from wandb import env
from wandb.errors import AuthenticationError, UsageError, term
from wandb.sdk import wandb_setup

from . import prompt, wbnetrc
from .auth import Auth, AuthApiKey, AuthIdentityTokenFile, AuthWithSource
from .host_url import HostUrl

_session_auth_lock = threading.Lock()
_session_auth: Auth | None = None


def session_credentials(*, host: str | HostUrl) -> Auth | None:
    """Returns the configured session credentials.

    Returns None if session credentials are configured for a different host.
    """
    with _session_auth_lock:
        if _session_auth and _session_auth.host.is_same_url(host):
            return _session_auth
        else:
            return None


def _locked_set_session_auth(
    auth: Auth | None,
    *,
    update_settings: bool = True,
) -> None:
    """Update session credentials.

    Updates the global _session_auth variable and the global settings.
    This is a refactoring step to transition away from storing auth in settings.

    Args:
        update_settings: Defaults to true. If false, skips updating the global
            settings (which may cause them to be loaded).
    """
    global _session_auth
    _session_auth = auth

    if not update_settings:
        return

    settings = wandb_setup.singleton().settings

    if auth is None:
        settings.api_key = None
        settings.identity_token_file = None

    elif isinstance(auth, AuthApiKey):
        settings.api_key = auth.api_key
        settings.identity_token_file = None
        settings.base_url = str(auth.host)

    elif isinstance(auth, AuthIdentityTokenFile):
        settings.api_key = None
        settings.identity_token_file = str(auth.path)
        settings.credentials_file = str(auth.credentials_path)
        settings.base_url = str(auth.host)

    else:
        raise NotImplementedError(str(auth))


def unauthenticate_session(*, update_settings: bool = True) -> Auth | None:
    """Clear the session credentials.

    Args:
        update_settings: Defaults to true. If false, skips updating the global
            settings (which may cause them to be loaded).

    Returns:
        The previous credentials, if any.
    """
    with _session_auth_lock:
        auth = _session_auth
        _locked_set_session_auth(None, update_settings=update_settings)
        return auth


def authenticate_session(
    *,
    host: str | HostUrl,
    source: str,
    no_offline: bool = False,
    no_create: bool = False,
    input_timeout: float | None = None,
    referrer: str = "models",
    relogin: bool = False,
) -> Auth | None:
    """Returns or configures the session credentials.

    If the session credentials are already configured for the given host,
    returns them. Otherwise, uses system credentials or prompts interactively.

    The return value is only None if the user selected offline mode in
    the interactive prompt.

    Args:
        host: The W&B server URL.
        source: The source to include in printed messages,
            like "wandb.init()".
        no_offline: Whether to show an offline option in interactive prompts.
        no_create: Whether to show a new account option in interactive prompts.
        input_timeout: A timeout for interactive prompts to avoid hanging
            the process if we incorrectly identify it as interactive.
        referrer: Referrer parameter to add to printed URLs for analytics.
        relogin: If true, forces an interactive prompt.

    Raises:
        TimeoutError: If an interactive prompt is shown and input_timeout expires.
        AuthenticationError: If credentials are found but have an invalid format.
        UsageError: If interactive prompting is needed but unavailable.
    """
    if not isinstance(host, HostUrl):
        host = HostUrl(host)

    if not relogin and (auth := session_credentials(host=host)):
        return auth

    if not relogin and (auth := _use_system_auth(host=host, source=source)):
        return auth

    try:
        return _use_prompted_auth(
            host=host,
            no_offline=no_offline,
            no_create=no_create,
            referrer=referrer,
            input_timeout=input_timeout,
        )
    except term.NotATerminalError:
        raise UsageError(
            "No API key configured. Use `wandb login` to log in."
        ) from None


def use_explicit_auth(auth: Auth, *, source: str) -> None:
    """Use explicitly given credentials in the session.

    Args:
        auth: Credentials to use.
        source: The source to include in the printed message,
            like "wandb.init()".
    """
    with _session_auth_lock:
        if _session_auth == auth:
            return

        if _session_auth:
            term.termwarn(
                f"[{source}] Changing session credentials to explicit value"
                + f" for {auth.host}."
            )
        else:
            term.termlog(
                f"[{source}] Using explicit session credentials for {auth.host}."
            )

        _locked_set_session_auth(auth)


def _use_system_auth(*, host: HostUrl, source: str) -> Auth | None:
    """Load (or reload) session credentials from external sources.

    Loads credentials from environment variables or the .netrc file.
    If no credentials are found, the session credentials are unchanged.

    Args:
        host: The W&B server URL.
        source: The source to include in the printed message,
            like "wandb.init()".

    Raises:
        AuthenticationError: If a source of credentials is found but has an
            invalid format.

    Returns:
        The new credentials, if any.
    """
    auth = (
        _try_env_auth(host=host)  #
        or wbnetrc.read_netrc_auth_with_source(host=host)
    )

    with _session_auth_lock:
        if auth:
            term.termlog(
                f"[{source}] Loaded credentials for {auth.auth.host}"
                + f" from {auth.source}."
            )
            _locked_set_session_auth(auth.auth)

        return _session_auth


def _try_env_auth(*, host: HostUrl) -> AuthWithSource | None:
    """Returns credentials from environment variables, if set.

    Raises an authentication error if an invalid combination of environment
    variables is set.
    """
    api_key = os.getenv(env.API_KEY)
    identity_token_file = os.getenv(env.IDENTITY_TOKEN_FILE)

    if api_key and identity_token_file:
        raise AuthenticationError(
            f"Both {env.API_KEY} and {env.IDENTITY_TOKEN_FILE} are set,"
            + " which is not allowed."
        )

    if api_key:
        try:
            return AuthWithSource(
                auth=AuthApiKey(host=host, api_key=api_key),
                source=env.API_KEY,
            )
        except AuthenticationError as e:
            raise AuthenticationError(f"{env.API_KEY} invalid: {e}") from None

    elif identity_token_file:
        return AuthWithSource(
            auth=AuthIdentityTokenFile(
                host=host,
                path=identity_token_file,
                credentials_file=wandb_setup.singleton().settings.credentials_file,
            ),
            source=env.IDENTITY_TOKEN_FILE,
        )

    return None


def _use_prompted_auth(
    *,
    host: HostUrl,
    no_offline: bool,
    no_create: bool,
    referrer: str,
    input_timeout: float | None = None,
) -> Auth | None:
    """Prompt interactively to set session credentials.

    May clear session credentials if the user selects offline mode.

    Args:
        host: The W&B server URL.
        no_offline: If true, do not show an option to skip logging in.
        no_create: If true, do not show an option to create a new account.
        referrer: Referrer parameter to include in printed URLs for analytics.
        input_timeout: How long to wait for user input before timing out.

    Raises:
        NotATerminalError: If interactive prompting is not possible.
        TimeoutError: If input_timeout expires.
    """
    api_key = prompt.prompt_and_save_api_key(
        host=host,
        no_offline=no_offline,
        no_create=no_create,
        referrer=referrer,
        input_timeout=input_timeout,
    )

    with _session_auth_lock:
        if api_key:
            _locked_set_session_auth(AuthApiKey(host=host, api_key=api_key))
        else:
            # Offline mode selected.
            _locked_set_session_auth(None)

        return _session_auth
