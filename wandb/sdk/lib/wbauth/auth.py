from __future__ import annotations

import abc
import dataclasses
import pathlib

from typing_extensions import final, override

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

    def fetch_access_token(self, credentials_path: pathlib.Path) -> str:
        """Fetch an access token for authenticating with the W&B server.

        Retrieves a valid access token from the credentials file. If no token
        exists or the existing token has expired, exchanges the identity token
        (JWT) from the configured token file for a new access token from the
        server and caches it in the credentials file.

        This method is used for OIDC-based authentication flows where a
        service account or workload identity provides a JWT that can be
        exchanged for a W&B access token.

        Args:
            credentials_path: The path to the credentials file used to cache
                access tokens. This file stores tokens keyed by server URL and
                includes expiration metadata to enable automatic refresh.

        Returns:
            A valid access token string that can be used for Bearer authentication
            with the W&B API.

        Raises:
            FileNotFoundError: If the identity token file does not exist.
            OSError: If there is an error reading the identity token file.
            AuthenticationError: If the server rejects the identity token or
                fails to provide an access token.
        """
        base_url = str(self.host.url)
        token_file = self.path

        return credentials.access_token(base_url, token_file, credentials_path)


@dataclasses.dataclass(frozen=True)
class AuthWithSource:
    """Credentials with information about where they came from."""

    auth: Auth

    source: str
    """A file path or environment variable."""
