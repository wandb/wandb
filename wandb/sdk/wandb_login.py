"""Log in to Weights & Biases.

This authenticates your machine to log data to your account.
"""

from __future__ import annotations

import enum
import os
from typing import Literal

import click
from requests.exceptions import ConnectionError

import wandb
from wandb.errors import AuthenticationError, UsageError
from wandb.old.settings import Settings as OldSettings

from ..apis import InternalApi
from .internal.internal_api import Api
from .lib import apikey


def _handle_host_wandb_setting(host: str | None = None) -> None:
    """Write the host parameter to the global settings file.

    This takes the parameter from wandb.login or wandb login for use by the
    application's APIs.
    """
    _api = InternalApi()
    if host == "https://api.wandb.ai" or host is None:
        _api.clear_setting("base_url", globally=True, persist=True)
        # To avoid writing an empty local settings file, we only clear if it exists
        if os.path.exists(OldSettings._local_path()):
            _api.clear_setting("base_url", persist=True)
    elif host:
        host = host.rstrip("/")
        # force relogin if host is specified
        _api.set_setting("base_url", host, globally=True, persist=True)


def login(
    anonymous: Literal["must", "allow", "never"] | None = None,
    key: str | None = None,
    relogin: bool | None = None,
    host: str | None = None,
    force: bool | None = None,
    timeout: int | None = None,
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
        force=force,
        host=host,
        key=key,
        relogin=relogin,
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
        anonymous: Literal["must", "allow", "never"] | None = None,
        force: bool | None = None,
        host: str | None = None,
        key: str | None = None,
        relogin: bool | None = None,
        timeout: int | None = None,
    ):
        self.login_settings = {
            "anonymous": anonymous,
            "api_key": key,
            "base_url": host,
            "force": force,
            "login_timeout": timeout,
            "relogin": relogin,
        }
        self.is_anonymous = anonymous == "must"

        self._wandb_setup = wandb.setup()
        self._wandb_setup.settings.update_from_dict(self.login_settings)
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
        self._settings.update_from_dict(login_settings)
        # Whenever the key changes, make sure to pull in user settings
        # from server.
        if not self._settings._offline:
            self._wandb_setup._update_user_settings()

    def configure_api_key(
        self,
        key: str | None = None,
    ) -> None:
        """Saves the API key and updates the the global setup object."""
        if self._settings._notebook and not self._settings.silent:
            wandb.termwarn(
                "If you're specifying your api key in code, ensure this "
                "code is not shared publicly.\nConsider setting the "
                "WANDB_API_KEY environment variable, or running "
                "`wandb login` from the command line."
            )
        if key:
            apikey.write_key(
                self._settings,
                key,
                anonymous=self.is_anonymous,
            )

    def _prompt_api_key(self) -> tuple[str | None, ApiKeyStatus]:
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

    def prompt_api_key(self) -> tuple[str | None, ApiKeyStatus]:
        """Gets and returns the API key from the user."""
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
        try:
            is_api_key_valid = (
                apikey.is_key_valid_length_api_key(key)
                and InternalApi(api_key=key).validate_api_key()
            )

            if not is_api_key_valid:
                raise AuthenticationError(
                    "API key verification failed. Make sure your API key is valid."
                )
        except AuthenticationError as ae:
            raise ae
        except ConnectionError:
            raise AuthenticationError(
                "Unable to connect to server to verify API token."
            )
        except Exception:
            raise AuthenticationError("An error occurred while verifying the API key.")


def _login(
    *,
    anonymous: Literal["must", "allow", "never"] | None = None,
    force: bool | None = None,
    host: str | None = None,
    key: str | None = None,
    relogin: bool | None = None,
    timeout: int | None = None,
    verify: bool = False,
    _disable_warning: bool | None = None,
    _silent: bool | None = None,
):
    if wandb.run is not None:
        if not _disable_warning:
            wandb.termwarn("Calling wandb.login() after wandb.init() has no effect.")
        return

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

    if wlogin._settings.identity_token_file is not None:
        return True

    key_is_pre_configured = False
    key_status = None
    if key is None:
        # Check if key is already set in the settings, or configured in the users .netrc file.
        key = apikey.api_key(settings=wlogin._settings)
        if key:
            key_is_pre_configured = True
        else:
            # Otherwise prompt the user for an API key.
            key, key_status = wlogin.prompt_api_key()

    if verify:
        wlogin._verify_login(key)

    if not key_is_pre_configured:
        wlogin.configure_api_key(key)
        wlogin.update_session(key, key_status)

    if key and not _silent:
        wlogin._print_logged_in_message()

    return key is not None
