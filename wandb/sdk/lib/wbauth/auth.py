from __future__ import annotations

import abc
import dataclasses
import pathlib

import requests
import requests.auth
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

    @abc.abstractmethod
    def as_requests_auth(self) -> requests.auth.AuthBase:
        """Return a requests-compatible auth handler for this credential.

        Returns a callable that implements the requests library's AuthBase
        interface. This can be passed directly to requests.Session.auth for
        automatic authentication on each request.

        For token-based auth (e.g., identity tokens), the returned handler
        will automatically refresh expired tokens on each request.

        Returns:
            A requests.auth.AuthBase instance that applies this credential
            to HTTP requests.
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
    def as_requests_auth(self) -> requests.auth.AuthBase:
        """Return a requests auth handler using HTTP Basic Auth.

        Returns:
            An auth handler that sets the Authorization header with
            Basic auth using "api" as the username and the API key
            as the password.
        """
        return requests.auth.HTTPBasicAuth("api", self._api_key)


class _IdentityTokenAuth(requests.auth.AuthBase):
    """Requests auth handler for identity token (JWT) authentication."""

    def __init__(self, auth: AuthIdentityTokenFile) -> None:
        self._auth = auth

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        token = self._auth.fetch_access_token()
        r.headers["Authorization"] = f"Bearer {token}"
        return r


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
        self._identity_token_file = pathlib.Path(path)
        self._credentials_path = pathlib.Path(credentials_file)

    @property
    def path(self) -> pathlib.Path:
        """Path to a file storing a JWT identity token."""
        return self._identity_token_file

    @property
    def credentials_path(self) -> pathlib.Path:
        """Path to the credentials file for caching access tokens."""
        return self._credentials_path

    def fetch_access_token(self) -> str:
        """Fetch an access token for authenticating with the W&B server.

        Retrieves a valid access token from the credentials file. If no token
        exists or the existing token has expired, exchanges the identity token
        (JWT) from the configured token file for a new access token from the
        server and caches it in the credentials file.

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
        return credentials.access_token(base_url, self.path, self.credentials_path)

    @override
    def as_requests_auth(self) -> requests.auth.AuthBase:
        """Return a requests auth handler using Bearer token authentication.

        The returned handler calls fetch_access_token() on each request,
        ensuring that expired tokens are automatically refreshed.

        Returns:
            An auth handler that sets the Authorization header with
            a Bearer token fetched (and refreshed as needed) from the
            identity token file.
        """
        return _IdentityTokenAuth(self)


@dataclasses.dataclass(frozen=True)
class AuthWithSource:
    """Credentials with information about where they came from."""

    auth: Auth

    source: str
    """A file path or environment variable."""
