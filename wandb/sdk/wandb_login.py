"""Log in to Weights & Biases.

This authenticates your machine to log data to your account.
"""

import enum
import os
import sys
from typing import Optional, Tuple

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

import click

import wandb
from wandb.errors import AuthenticationError, UsageError
from wandb.old.settings import Settings as OldSettings

from ..apis import InternalApi
from .internal.internal_api import Api
from .lib import apikey
from .wandb_settings import Settings


def _handle_host_wandb_setting(host: Optional[str], cloud: bool = False) -> None:
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


def login(
    anonymous: Optional[Literal["must", "allow", "never"]] = None,
    key: Optional[str] = None,
    relogin: Optional[bool] = None,
    host: Optional[str] = None,
    force: Optional[bool] = None,
    timeout: Optional[int] = None,
    verify: bool = False,
) -> bool:
    """Set up W&B login credentials.

    By default, this will only store credentials locally without
    verifying them with the W&B server. To verify credentials, pass
    `verify=True`.

    Arguments:
        anonymous: (string, optional) Can be "must", "allow", or "never".
            If set to "must", always log a user in anonymously. If set to
            "allow", only create an anonymous user if the user
            isn't already logged in. If set to "never", never log a
            user anonymously. Default set to "never".
        relogin: (bool, optional) If true, will re-prompt for API key.
        host: (string, optional) The host to connect to.
        force: (bool, optional) If true, will force a relogin.
        timeout: (int, optional) Number of seconds to wait for user input.
        verify: (bool) Verify the credentials with the W&B server.

    Returns:
        bool: if key is configured

    Raises:
        AuthenticationError - if api_key fails verification with the server
        UsageError - if api_key cannot be configured and no tty
    """
    _handle_host_wandb_setting(host)
    if wandb.setup()._settings._noop:
        return True

    configured = _login(
        anonymous=anonymous,
        key=key,
        relogin=relogin,
        host=host,
        force=force,
        timeout=timeout,
    )

    if verify:
        from . import wandb_setup

        singleton = wandb_setup._WandbSetup._instance
        assert singleton is not None
        viewer = singleton._server._viewer
        if not viewer:
            raise AuthenticationError(
                "API key verification failed. Make sure your API key is valid."
            )
    return True if configured else False


class ApiKeyStatus(enum.Enum):
    VALID = 1
    NOTTY = 2
    OFFLINE = 3
    DISABLED = 4


class _WandbLogin:
    def __init__(self):
        self._settings: Optional[Settings] = None
        self._backend = None
        self._silent: Optional[bool] = None
        self._entity: Optional[str] = None
        self._wl = None
        self._key = None
        self._relogin = None

    def setup(
        self,
        *,
        anonymous: Optional[Literal["must", "allow", "never"]] = None,
        key: Optional[str] = None,
        relogin: Optional[bool] = None,
        host: Optional[str] = None,
        force: Optional[bool] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """Updates login-related settings on the global setup object."""
        self._relogin = relogin

        # built up login settings
        login_settings: Settings = wandb.Settings()
        logger = wandb.setup()._get_logger()

        login_settings._apply_login(
            {
                "anonymous": anonymous,
                "key": key,
                "host": host,
                "force": force,
                "timeout": timeout,
            },
            _logger=logger,
        )

        # make sure they are applied globally
        self._wl = wandb.setup(settings=login_settings)
        self._settings = self._wl.settings

    def is_apikey_configured(self) -> bool:
        """Returns whether an API key is set or can be inferred."""
        return apikey.api_key(settings=self._settings) is not None

    def should_use_identity_token(self):
        return self._settings.identity_token_file is not None

    def set_backend(self, backend):
        self._backend = backend

    def set_silent(self, silent: bool) -> None:
        self._silent = silent

    def set_entity(self, entity: str) -> None:
        self._entity = entity

    def login(self) -> bool:
        """Returns whether the user is logged in (i.e. an API key exists).

        If the user is logged in, this also prints an informational message.
        """
        apikey_configured = self.is_apikey_configured()
        if self._settings.relogin or self._relogin:
            apikey_configured = False
        if not apikey_configured:
            return False

        if not self._silent:
            self._print_logged_in_message()

        return apikey_configured

    def _print_logged_in_message(self) -> None:
        """Prints a message telling the user they are logged in."""
        username = self._wl._get_username()

        if username:
            # check to see if we got an entity from the setup call or from the user
            entity = self._entity or self._wl._get_entity()

            entity_str = ""
            # check if entity exist, valid (is part of a certain team) and different from the username
            if entity and entity in self._wl._get_teams() and entity != username:
                entity_str = f" ({click.style(entity, fg='yellow')})"

            login_state_str = f"Currently logged in as: {click.style(username, fg='yellow')}{entity_str}"
        else:
            login_state_str = "W&B API key is configured"

        login_info_str = (
            f"Use {click.style('`wandb login --relogin`', bold=True)} to force relogin"
        )
        wandb.termlog(
            f"{login_state_str}. {login_info_str}",
            repeat=False,
        )

    def configure_api_key(self, key: str) -> None:
        """Saves the API key and updates the the global setup object."""
        if self._settings._notebook and not self._settings.silent:
            wandb.termwarn(
                "If you're specifying your api key in code, ensure this "
                "code is not shared publicly.\nConsider setting the "
                "WANDB_API_KEY environment variable, or running "
                "`wandb login` from the command line."
            )
        apikey.write_key(self._settings, key)
        self.update_session(key)
        self._key = key

    def update_session(
        self,
        key: Optional[str],
        status: ApiKeyStatus = ApiKeyStatus.VALID,
    ) -> None:
        """Updates mode and API key settings on the global setup object.

        If we're online, this also pulls in user settings from the server.
        """
        _logger = wandb.setup()._get_logger()
        login_settings = dict()
        if status == ApiKeyStatus.OFFLINE:
            login_settings = dict(mode="offline")
        elif status == ApiKeyStatus.DISABLED:
            login_settings = dict(mode="disabled")
        elif key:
            login_settings = dict(api_key=key)
        self._wl._settings._apply_login(login_settings, _logger=_logger)
        # Whenever the key changes, make sure to pull in user settings
        # from server.
        if not self._wl.settings._offline:
            self._wl._update_user_settings()

    def _prompt_api_key(self) -> Tuple[Optional[str], ApiKeyStatus]:
        api = Api(self._settings)
        while True:
            try:
                key = apikey.prompt_api_key(
                    self._settings,
                    api=api,
                    no_offline=self._settings.force if self._settings else None,
                    no_create=self._settings.force if self._settings else None,
                )
            except ValueError as e:
                # invalid key provided, try again
                wandb.termerror(e.args[0])
                continue
            except TimeoutError:
                wandb.termlog("W&B disabled due to login timeout.")
                return None, ApiKeyStatus.DISABLED
            if key is False:
                return None, ApiKeyStatus.NOTTY
            if not key:
                return None, ApiKeyStatus.OFFLINE
            return key, ApiKeyStatus.VALID

    def prompt_api_key(self) -> None:
        """Updates the global API key by prompting the user."""
        key, status = self._prompt_api_key()
        if status == ApiKeyStatus.NOTTY:
            directive = (
                "wandb login [your_api_key]"
                if self._settings._cli_only_mode
                else "wandb.login(key=[your_api_key])"
            )
            raise UsageError("api_key not configured (no-tty). call " + directive)

        self.update_session(key, status=status)
        self._key = key


def _login(
    *,
    anonymous: Optional[Literal["must", "allow", "never"]] = None,
    key: Optional[str] = None,
    relogin: Optional[bool] = None,
    host: Optional[str] = None,
    force: Optional[bool] = None,
    timeout: Optional[int] = None,
    _backend=None,
    _silent: Optional[bool] = None,
    _disable_warning: Optional[bool] = None,
    _entity: Optional[str] = None,
):
    if wandb.run is not None:
        if not _disable_warning:
            wandb.termwarn("Calling wandb.login() after wandb.init() has no effect.")
        return True

    wlogin = _WandbLogin()

    if _backend:
        wlogin.set_backend(_backend)

    if _silent:
        wlogin.set_silent(_silent)

    if _entity:
        wlogin.set_entity(_entity)

    # configure login object
    wlogin.setup(
        anonymous=anonymous,
        key=key,
        relogin=relogin,
        host=host,
        force=force,
        timeout=timeout,
    )

    if wlogin._settings._offline:
        return False
    elif wandb.util._is_kaggle() and not wandb.util._has_internet():
        wandb.termerror(
            "To use W&B in kaggle you must enable internet in the settings panel on the right."
        )
        return False

    if wlogin.should_use_identity_token():
        return True

    # perform a login
    logged_in = wlogin.login()

    if key:
        wlogin.configure_api_key(key)

    if logged_in:
        return logged_in

    if not key:
        wlogin.prompt_api_key()

    return wlogin._key or False
