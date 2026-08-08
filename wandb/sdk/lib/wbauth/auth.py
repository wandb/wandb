from __future__ import annotations

import abc
import dataclasses
import pathlib

from typing_extensions import final, override

from wandb.errors import AuthenticationError

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

    @abc.abstractmethod
    def verify(self) -> None:
        """Verify the credentials against the W&B server.

        Raises:
            AuthenticationError: If the credentials are invalid.
        """

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

    @override
    def verify(self) -> None:
        """Verify the credentials against the W&B server."""
        if problems := validation.check_api_key_validity(
            api_key=self._api_key,
            host=self.host,
        ):
            raise AuthenticationError(problems)


@final
class AuthIdentityTokenFile(Auth):
    """A path to a file storing a JWT with OIDC credentials."""

    @override
    def __init__(
        self,
        *,
        host: str | HostUrl,
        path: str,
        credentials_file: str,
    ) -> None:
        """Initialize AuthIdentityTokenFile.

        Args:
            host: The W&B server URL.
            path: Path to the identity token file containing a JWT.
            credentials_file: Path to the credentials file for caching access tokens.
        """
        super().__init__(host=host)

        # Store absolute paths: the files may be read and written by the
        # wandb-core service process, whose working directory can differ
        # from this process's.
        self._identity_token_file = pathlib.Path(path).absolute()
        self._credentials_path = pathlib.Path(credentials_file).absolute()

    @property
    def path(self) -> pathlib.Path:
        """Path to a file storing a JWT identity token."""
        return self._identity_token_file

    @property
    def credentials_path(self) -> pathlib.Path:
        """Path to the credentials file for caching access tokens."""
        return self._credentials_path

    @override
    def verify(self) -> None:
        """Verify the credentials against the W&B server."""
        if problems := validation.check_identity_token_validity(
            host=self.host,
            identity_token_file=self._identity_token_file,
            credentials_file=self._credentials_path,
        ):
            raise AuthenticationError(problems)


@dataclasses.dataclass(frozen=True)
class AuthWithSource:
    """Credentials with information about where they came from."""

    auth: Auth

    source: str
    """A file path or environment variable."""
