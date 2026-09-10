from __future__ import annotations

import os
import pathlib
import threading

from wandb import env
from wandb.errors import AuthenticationError, UsageError, term
from wandb.sdk import wandb_setup

from . import identity_token_file, prompt, wbnetrc
from .auth import Auth, AuthApiKey, AuthIdentityTokenFile, AuthWithSource
from .host_url import HostUrl
from .settings import set_auth_settings

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

    if update_settings:
        set_auth_settings(wandb_setup.singleton().settings, auth)


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
    verify: bool = False,
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
        verify: If true, verifies the credentials against the W&B server.

    Raises:
        TimeoutError: If an interactive prompt is shown and input_timeout expires.
        AuthenticationError: If credentials are found but have an invalid format.
        UsageError: If interactive prompting is needed but unavailable.
    """
    if not isinstance(host, HostUrl):
        host = HostUrl(host)

    if not relogin and (auth := session_credentials(host=host)):
        return auth

    if not relogin and (
        auth := _use_system_auth(
            host=host,
            source=source,
            verify=verify,
        )
    ):
        return auth

    try:
        return _use_prompted_auth(
            host=host,
            no_offline=no_offline,
            no_create=no_create,
            referrer=referrer,
            input_timeout=input_timeout,
            verify=verify,
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


def _use_system_auth(
    *,
    host: HostUrl,
    source: str,
    verify: bool = False,
) -> Auth | None:
    """Load (or reload) session credentials from external sources.

    Loads federated-identity credentials from the identity-token environment
    variable, persisted setting, or default token path. When an API-key
    environment variable is also configured, federated identity takes
    precedence and a warning is printed. If no identity token is configured,
    it loads an API key from the environment or .netrc file.

    Args:
        host: The W&B server URL.
        source: The source to include in the printed message,
            like "wandb.init()".
        verify: If true, verifies the credentials against the W&B server.

    Raises:
        AuthenticationError: If a source of credentials is found but has an
            invalid format.

    Returns:
        The new credentials, if any.
    """
    identity_token_auth = _try_identity_token_auth(host=host)
    api_key = os.getenv(env.API_KEY)
    if api_key and identity_token_auth:
        term.termwarn(
            f"Ignoring {env.API_KEY} because federated identity credentials"
            + f" are configured from {identity_token_auth.source}."
        )

    auth = (
        identity_token_auth
        or _try_env_api_key_auth(host=host)
        or wbnetrc.read_netrc_auth_with_source(host=host)
    )

    if verify and auth:
        auth.auth.verify()

    with _session_auth_lock:
        if auth:
            term.termlog(
                f"[{source}] Loaded credentials for {auth.auth.host}"
                + f" from {auth.source}."
            )
            _locked_set_session_auth(auth.auth)

        return _session_auth


def _try_identity_token_auth(*, host: HostUrl) -> AuthWithSource | None:
    """Returns identity-token credentials from their configured sources.

    The identity-token environment variable takes precedence over the persisted
    setting, which takes precedence over the standard config-directory path.
    The latter lets a preceding ``wandb login sso`` be used without setting an
    environment variable explicitly.
    """
    if path := os.getenv(env.IDENTITY_TOKEN_FILE):
        return _identity_token_auth(path, host=host, source=env.IDENTITY_TOKEN_FILE)

    if auth := _try_settings_file_auth(host=host):
        return auth

    default_path = identity_token_file.default_path()
    if _has_sso_account(default_path, host=host):
        return _identity_token_auth(default_path, host=host, source=_SSO_SOURCE)

    return None


_SSO_SOURCE = "your saved SSO credentials"


def _identity_token_auth(
    path: str | pathlib.Path,
    *,
    host: HostUrl,
    source: str,
) -> AuthWithSource:
    return AuthWithSource(
        auth=AuthIdentityTokenFile(
            host=host,
            path=str(path),
            credentials_file=wandb_setup.singleton().settings.credentials_file,
        ),
        source=source,
    )


def _has_sso_account(path: pathlib.Path, *, host: HostUrl) -> bool:
    """Returns whether ``path`` holds `wandb login sso` credentials for ``host``."""
    try:
        return identity_token_file.load(path).for_host(host) is not None
    except identity_token_file.AmbiguousAccountError as e:
        # Let another configured credential source work instead of blocking
        # every request until the saved accounts are sorted out.
        term.termwarn(str(e))
        return False
    except identity_token_file.InvalidIdentityTokenFileError:
        # This may be a bare JWT provisioned outside `wandb login sso`,
        # which has no host to match automatically.
        return False


def _try_env_api_key_auth(*, host: HostUrl) -> AuthWithSource | None:
    """Returns API-key credentials from the environment, if set."""
    api_key = os.getenv(env.API_KEY)
    if not api_key:
        return None

    try:
        return AuthWithSource(
            auth=AuthApiKey(host=host, api_key=api_key),
            source=env.API_KEY,
        )
    except AuthenticationError as e:
        raise AuthenticationError(f"{env.API_KEY} invalid: {e}") from None


def _try_settings_file_auth(*, host: HostUrl) -> AuthWithSource | None:
    """Returns identity-token credentials persisted for this host, if any."""
    settings = wandb_setup.singleton().settings

    if not settings.identity_token_file:
        return None
    if not HostUrl(settings.base_url).is_same_url(host):
        return None

    path = pathlib.Path(settings.identity_token_file)
    return _identity_token_auth(
        path,
        host=host,
        source=(
            _SSO_SOURCE
            if _has_sso_account(path, host=host)
            else f"an identity token file configured in your settings ({path})"
        ),
    )


def _use_prompted_auth(
    *,
    host: HostUrl,
    no_offline: bool,
    no_create: bool,
    referrer: str,
    input_timeout: float | None = None,
    verify: bool = True,
) -> Auth | None:
    """Prompt interactively to set session credentials.

    May clear session credentials if the user selects offline mode.

    Args:
        host: The W&B server URL.
        no_offline: If true, do not show an option to skip logging in.
        no_create: If true, do not show an option to create a new account.
        referrer: Referrer parameter to include in printed URLs for analytics.
        input_timeout: How long to wait for user input before timing out.
        verify: If true, verifies the credentials against the W&B server.

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
        verify=verify,
    )

    with _session_auth_lock:
        if api_key:
            _locked_set_session_auth(AuthApiKey(host=host, api_key=api_key))
        else:
            # Offline mode selected.
            _locked_set_session_auth(None)

        return _session_auth
