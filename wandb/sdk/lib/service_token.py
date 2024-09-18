from __future__ import annotations

import dataclasses
import os

from wandb import env

_CURRENT_VERSION = "2"
_SUPPORTED_TRANSPORTS = "tcp"


def get_service_token() -> ServiceToken | None:
    """Reads the token from environment variables.

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
            f"Expected version {_CURRENT_VERSION},"
            f" but got {version} (token={token})"
        )
    if transport not in _SUPPORTED_TRANSPORTS:
        raise ValueError(
            f"Unsupported transport: {transport} (token={token})",
        )

    try:
        return ServiceToken(
            version=version,
            pid=int(pid_str),
            transport=transport,
            host=host,
            port=int(port_str),
        )
    except ValueError as e:
        raise ValueError(f"Invalid token: {token}") from e


def set_service_token(parent_pid: int, transport: str, host: str, port: int) -> None:
    """Stores a service token in an environment variable.

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


def clear_service_token() -> None:
    """Clears the environment variable storing the service token."""
    os.environ.pop(env.SERVICE, None)


@dataclasses.dataclass(frozen=True)
class ServiceToken:
    """An identifier for a running service process."""

    version: str
    pid: int
    transport: str
    host: str
    port: int
