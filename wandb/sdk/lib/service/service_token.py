from __future__ import annotations

import abc
import asyncio
import os
import re

from typing_extensions import final, override

from wandb import env
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service import ipc_support

from .service_client import ServiceClient

_CURRENT_VERSION = "3"

# Token formats:
_UNIX_TOKEN_RE = re.compile(rf"{_CURRENT_VERSION}-(\d+)-unix-(.+)")
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

    if unix_token := UnixServiceToken.from_env_string(token):
        return unix_token
    if tcp_token := TCPServiceToken.from_env_string(token):
        return tcp_token

    raise ValueError(f"Failed to parse {env.SERVICE}={token!r}")


class ServiceToken(abc.ABC):
    """A way of connecting to a running service process."""

    @abc.abstractmethod
    def connect(
        self,
        *,
        asyncer: asyncio_manager.AsyncioManager,
    ) -> ServiceClient:
        """Connect to the service process.

        Args:
            asyncer: A started AsyncioManager for asyncio operations.

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
class UnixServiceToken(ServiceToken):
    """Connects to the service using a Unix domain socket."""

    def __init__(self, *, parent_pid: int, path: str) -> None:
        self._parent_pid = parent_pid
        self._path = path

    @override
    def connect(
        self,
        *,
        asyncer: asyncio_manager.AsyncioManager,
    ) -> ServiceClient:
        if not ipc_support.SUPPORTS_UNIX:
            raise WandbServiceConnectionError("AF_UNIX socket not supported")

        try:
            # TODO: This may block indefinitely if the service is unhealthy.
            reader, writer = asyncer.run(
                lambda: asyncio.open_unix_connection(self._path),
            )
        except Exception as e:
            raise WandbServiceConnectionError(
                f"Failed to connect to service on socket {self._path}",
            ) from e

        return ServiceClient(asyncer, reader, writer)

    @override
    def _as_env_string(self):
        return "-".join(
            (
                _CURRENT_VERSION,
                str(self._parent_pid),
                "unix",
                str(self._path),
            )
        )

    @staticmethod
    def from_env_string(token: str) -> UnixServiceToken | None:
        """Returns a Unix service token parsed from the env var."""
        match = _UNIX_TOKEN_RE.fullmatch(token)
        if not match:
            return None

        parent_pid, path = match.groups()
        return UnixServiceToken(parent_pid=int(parent_pid), path=path)


@final
class TCPServiceToken(ServiceToken):
    """Connects to the service using TCP over a localhost socket."""

    def __init__(self, *, parent_pid: int, port: int) -> None:
        self._parent_pid = parent_pid
        self._port = port

    @override
    def connect(
        self,
        *,
        asyncer: asyncio_manager.AsyncioManager,
    ) -> ServiceClient:
        try:
            # TODO: This may block indefinitely if the service is unhealthy.
            reader, writer = asyncer.run(
                lambda: asyncio.open_connection("localhost", self._port),
            )
        except Exception as e:
            raise WandbServiceConnectionError(
                f"Failed to connect to service on port {self._port}",
            ) from e

        return ServiceClient(asyncer, reader, writer)

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
