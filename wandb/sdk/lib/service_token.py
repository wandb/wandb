from __future__ import annotations

import dataclasses
import os

from wandb import env
from wandb.sdk.lib.sock_client import SockClient

_CURRENT_VERSION = "2"
_SUPPORTED_TRANSPORTS = ("tcp",)


class WandbServiceConnectionError(Exception):
    """Failed to connect to the service process."""


def connect_to_service_in_env() -> SockClient | None:
    """Connect to the service specified in environment variables.

    Returns:
        A socket client connected to the service if the correct environment
        variable is set, or None.

    Raises:
        ValueError: If the environment variable is set but cannot be
            parsed.
        WandbServiceConnectionError: if the environment variable is set, but
            we fail to connect to the service.
    """
    token = _get_service_token()  # May raise ValueError.
    if not token:
        return None

    if token.host != "localhost":
        raise WandbServiceConnectionError(f"Cannot connect to {token}")

    client = SockClient()

    try:
        # TODO: This may block indefinitely if the service is unhealthy.
        client.connect(token.port)
    except Exception as e:
        raise WandbServiceConnectionError(f"Failed to connect to {token}") from e

    return client


def set_service_in_env(parent_pid: int, transport: str, host: str, port: int) -> None:
    """Store a service token in an environment variable.

    Args:
        parent_pid: The process ID of the process that started the service.
        transport: The transport used to communicate with the service.
        host: The host part of the internet address on which the service
            is listening (e.g. localhost).
        port: The port the service is listening on.

    Raises:
        ValueError: If given an unsupported transport.
    """
    if transport not in _SUPPORTED_TRANSPORTS:
        raise ValueError(f"Unsupported transport: {transport}")

    os.environ[env.SERVICE] = "-".join(
        (
            _CURRENT_VERSION,
            str(parent_pid),
            transport,
            host,
            str(port),
        )
    )


def clear_service_in_env() -> None:
    """Clear the environment variable storing the service token."""
    os.environ.pop(env.SERVICE, None)


def _get_service_token() -> _ServiceToken | None:
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

    parts = token.split("-")
    if len(parts) != 5:
        raise ValueError(f"Invalid token: {token}")

    version, pid_str, transport, host, port_str = parts

    if version != _CURRENT_VERSION:
        raise ValueError(
            f"Expected version {_CURRENT_VERSION}, but got {version} (token={token})"
        )
    if transport not in _SUPPORTED_TRANSPORTS:
        raise ValueError(
            f"Unsupported transport: {transport} (token={token})",
        )

    try:
        return _ServiceToken(
            version=version,
            pid=int(pid_str),
            transport=transport,
            host=host,
            port=int(port_str),
        )
    except ValueError as e:
        raise ValueError(f"Invalid token: {token}") from e


@dataclasses.dataclass(frozen=True)
class _ServiceToken:
    """An identifier for a running service process."""

    version: str
    pid: int
    transport: str
    host: str
    port: int
