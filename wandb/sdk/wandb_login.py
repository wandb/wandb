"""Log in to Weights & Biases.

This authenticates your machine to log data to your account.
"""

import enum
import os
from typing import Literal, Optional, Tuple

import click
from requests.exceptions import ConnectionError

import wandb
from wandb.errors import AuthenticationError, UsageError
from wandb.old.settings import Settings as OldSettings

from ..apis import InternalApi
from .internal.internal_api import Api
from .lib import apikey


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

    Args:
        anonymous: (string, optional) Can be "must", "allow", or "never".
            If set to "must", always log a user in anonymously. If set to
            "allow", only create an anonymous user if the user
            isn't already logged in. If set to "never", never log a
            user anonymously. Default set to "never".
        key: (string, optional) The API key to use.
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
    return _login(
        anonymous=anonymous,
        key=key,
        relogin=relogin,
        host=host,
        force=force,
        timeout=timeout,
        verify=verify,
    )


class ApiKeyStatus(enum.Enum):
    VALID = 1
    NOTTY = 2
    OFFLINE = 3
    DISABLED = 4


class _WandbLogin:
    def __init__(
        self,
        anonymous: Optional[Literal["must", "allow", "never"]] = None,
        force: Optional[bool] = None,
        host: Optional[str] = None,
        key: Optional[str] = None,
        relogin: Optional[bool] = None,
        timeout: Optional[int] = None,
    ):
        self._relogin = relogin

        login_settings = {
            "anonymous": anonymous,
            "api_key": key,
            "base_url": host,
            "force": force,
            "login_timeout": timeout,
        }
        self.is_anonymous = anonymous == "must"

        self._wandb_setup = wandb.setup()
        self._wandb_setup.settings.update_from_dict(login_settings)
        self._settings = self._wandb_setup.settings

    def _update_global_anonymous_setting(self) -> None:
        api = InternalApi()
        if self.is_anonymous:
            api.set_setting("anonymous", "must", globally=True, persist=True)
        else:
            api.clear_setting("anonymous", globally=True, persist=True)

    def is_apikey_configured(self) -> bool:
        """Returns whether an API key is set or can be inferred."""
        return apikey.api_key(settings=self._settings) is not None

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
                "If you're specifying your api key in code, ensure this "
                "code is not shared publicly.\nConsider setting the "
                "WANDB_API_KEY environment variable, or running "
                "`wandb login` from the command line."
            )
        if key:
            try:
                apikey.write_key(self._settings, key)
            except apikey.WriteNetrcError as e:
                wandb.termwarn(str(e))

    def update_session(
        self,
        key: Optional[str],
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
            self._wandb_setup._update_user_settings()

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

    def prompt_api_key(self) -> Tuple[Optional[str], ApiKeyStatus]:
        """Updates the global API key by prompting the user."""
        key, status = self._prompt_api_key()
        if status == ApiKeyStatus.NOTTY:
            directive = (
                "wandb login [your_api_key]"
                if self._settings.x_cli_only_mode
                else "wandb.login(key=[your_api_key])"
            )
            raise UsageError("api_key not configured (no-tty). call " + directive)

        return key, status

    def _verify_login(self, key: str) -> None:
        api = InternalApi(api_key=key)

        try:
            is_api_key_valid = api.validate_api_key()

            if not is_api_key_valid:
                raise AuthenticationError(
                    "API key verification failed. Make sure your API key is valid."
                )
        except ConnectionError:
            raise AuthenticationError(
                "Unable to connect to server to verify API token."
            )
        except Exception:
            raise AuthenticationError("An error occurred while verifying the API key.")


def _login(
    *,
    anonymous: Optional[Literal["allow", "must", "never"]] = None,
    key: Optional[str] = None,
    relogin: Optional[bool] = None,
    host: Optional[str] = None,
    force: Optional[bool] = None,
    timeout: Optional[int] = None,
    verify: bool = False,
    _silent: Optional[bool] = None,
    _disable_warning: Optional[bool] = None,
) -> bool:
    if wandb.run is not None:
        if not _disable_warning:
            wandb.termwarn("Calling wandb.login() after wandb.init() has no effect.")
        return True

    wlogin = _WandbLogin(
        anonymous=anonymous,
        force=force,
        host=host,
        key=key,
        relogin=relogin,
        timeout=timeout,
    )

    if wlogin._settings._noop:
        return True

    if wlogin._settings._offline and not wlogin._settings.x_cli_only_mode:
        wandb.termwarn("Unable to verify login in offline mode.")
        return False
    elif wandb.util._is_kaggle() and not wandb.util._has_internet():
        wandb.termerror(
            "To use W&B in kaggle you must enable internet in the settings panel on the right."
        )
        return False

    if wlogin._settings.identity_token_file:
        return True

    key_is_pre_configured = False
    key_status = None
    if key is None:
        # Check if key is already set in the settings, or configured in the users .netrc file.
        key = apikey.api_key(settings=wlogin._settings)
        if key and not relogin:
            key_is_pre_configured = True
        else:
            key, key_status = wlogin.prompt_api_key()

    if verify:
        wlogin._verify_login(key)

    if not key_is_pre_configured:
        wlogin.try_save_api_key(key)
        wlogin.update_session(key, status=key_status)
        wlogin._update_global_anonymous_setting()

    if key and not _silent:
        wlogin._print_logged_in_message()

    return key is not None
