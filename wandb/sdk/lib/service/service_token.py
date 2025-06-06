from __future__ import annotations

import abc
import os
import re
import socket

from typing_extensions import final, override

from wandb import env
from wandb.sdk.lib.service import ipc_support
from wandb.sdk.lib.sock_client import SockClient

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
class UnixServiceToken(ServiceToken):
    """Connects to the service using a Unix domain socket."""

    def __init__(self, *, parent_pid: int, path: str) -> None:
        self._parent_pid = parent_pid
        self._path = path

    @override
    def connect(self) -> SockClient:
        if not ipc_support.SUPPORTS_UNIX:
            raise WandbServiceConnectionError("AF_UNIX socket not supported")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        try:
            # TODO: This may block indefinitely if the service is unhealthy.
            sock.connect(self._path)
        except Exception as e:
            raise WandbServiceConnectionError(
                f"Failed to connect to service on socket {self._path}",
            ) from e

        return SockClient(sock)

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
    def connect(self) -> SockClient:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            # TODO: This may block indefinitely if the service is unhealthy.
            sock.connect(("localhost", self._port))
        except Exception as e:
            raise WandbServiceConnectionError(
                f"Failed to connect to service on port {self._port}",
            ) from e

        return SockClient(sock)

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
