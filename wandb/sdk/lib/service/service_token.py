from __future__ import annotations

import abc
import os
import re

from typing_extensions import final, override

from wandb import env
from wandb.sdk.lib.sock_client import SockClient

_CURRENT_VERSION = "2"

# Token format(s):
_TCP_TOKEN_RE = re.compile(rf"{_CURRENT_VERSION}-(\d+)-tcp-localhost-(\d+)")


class WandbServiceConnectionError(Exception):
    """Failed to connect to the service process."""


def clear_service_in_env() -> None:
    """Clear the environment variable that stores the service token."""
    os.environ.pop(env.SERVICE, None)


def from_env() -> ServiceToken | None:
    """Read the token from environment variables.

    Returns:
        The token if the correct environment variable is set, or None.

    Raises:
        ValueError: If the environment variable is set but cannot be
            parsed.
    """
    token = os.environ.get(env.SERVICE)
    if not token:
        return None

    if tcp_token := TCPServiceToken.from_env_string(token):
        return tcp_token

    raise ValueError(f"Failed to parse {env.SERVICE}={token!r}")


class ServiceToken(abc.ABC):
    """A way of connecting to a running service process."""

    @abc.abstractmethod
    def connect(self) -> SockClient:
        """Connect to the service process.

        Returns:
            A socket object for communicating with the service.

        Raises:
            WandbServiceConnectionError: on failure to connect.
        """

    def save_to_env(self) -> None:
        """Save the token in this process's environment variables."""
        os.environ[env.SERVICE] = self._as_env_string()

    @abc.abstractmethod
    def _as_env_string(self) -> str:
        """Returns a string representation of this token."""


@final
class TCPServiceToken(ServiceToken):
    """Connects to the service using TCP over a localhost socket."""

    def __init__(self, *, parent_pid: int, port: int) -> None:
        self._parent_pid = parent_pid
        self._port = port

    @override
    def connect(self) -> SockClient:
        client = SockClient()

        try:
            # TODO: This may block indefinitely if the service is unhealthy.
            client.connect(self._port)
        except Exception as e:
            raise WandbServiceConnectionError(
                f"Failed to connect to service on port {self._port}",
            ) from e

        return client

    @override
    def _as_env_string(self):
        return "-".join(
            (
                _CURRENT_VERSION,
                str(self._parent_pid),
                "tcp",
                "localhost",
                str(self._port),
            )
        )

    @staticmethod
    def from_env_string(token: str) -> TCPServiceToken | None:
        """Returns a TCP service token parsed from the env var."""
        match = _TCP_TOKEN_RE.fullmatch(token)
        if not match:
            return None

        parent_pid, port = match.groups()
        return TCPServiceToken(parent_pid=int(parent_pid), port=int(port))
