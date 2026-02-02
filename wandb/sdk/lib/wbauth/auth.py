from __future__ import annotations

import abc
import dataclasses
import os
import pathlib
from typing import Mapping

from typing_extensions import final, override

from wandb import env as wandb_env
from wandb.errors import AuthenticationError
from wandb.sdk.lib import credentials

from . import validation
from .host_url import HostUrl


# We use an abstract base class instead of a union because
#   (1) All Auth subtypes have a 'host' property and a safe repr
#   (2) Auth should be treated as an open union, meaning typecheckers should
#       not consider any list of isinstance() checks exhaustive and should
#       always require a fallback case
class Auth(abc.ABC):
    """Credentials that give access to a W&B server."""

    @abc.abstractmethod
    def __init__(self, *, host: str | HostUrl) -> None:
        if isinstance(host, str):
            host = HostUrl(host)
        self._host = host

    @property
    def host(self) -> HostUrl:
        """The W&B server for which the credentials are valid."""
        return self._host

    @final
    @override
    def __repr__(self) -> str:
        return f"<{type(self).__name__} host={self.host.url!r}>"

    @final
    @override
    def __str__(self) -> str:
        return repr(self)


@final
class AuthApiKey(Auth):
    """An API key for connecting to a W&B server."""

    @override
    def __init__(self, *, host: str | HostUrl, api_key: str) -> None:
        """Initialize AuthApiKey.

        Args:
            host: The W&B server URL.
            api_key: The API key.

        Raises:
            ValueError: If the host is invalid.
            AuthenticationError: If the API key is in an invalid format.
        """
        super().__init__(host=host)

        if problems := validation.check_api_key(api_key):
            raise AuthenticationError(problems)

        self._api_key = api_key

    @property
    def api_key(self) -> str:
        """The API key."""
        return self._api_key


@final
class AuthIdentityTokenFile(Auth):
    """A path to a file storing a JWT with OIDC credentials."""

    @override
    def __init__(self, *, host: str | HostUrl, path: str) -> None:
        super().__init__(host=host)
        self._identity_token_file = pathlib.Path(path)

    @property
    def path(self) -> pathlib.Path:
        """Path to a file storing a JWT identity token."""
        return self._identity_token_file

    def get_access_token(self, env: Mapping[str, str] | None = None) -> str:
        if env is None:
            env = os.environ
        
        base_url = str(self.host.url)
        token_file = self.path
        credentials_file = wandb_env.get_credentials_file(
            str(credentials.DEFAULT_WANDB_CREDENTIALS_FILE), env
        )
        
        return credentials.access_token(base_url, token_file, pathlib.Path(credentials_file))


@dataclasses.dataclass(frozen=True)
class AuthWithSource:
    """Credentials with information about where they came from."""

    auth: Auth

    source: str
    """A file path or environment variable."""
