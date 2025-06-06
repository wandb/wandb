"""Module for figuring out how to connect to the service process."""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import time

import wandb

from . import ipc_support, service_token

# Time functions are monkeypatched in unit tests.
_MONOTONIC = time.monotonic
_SLEEP = time.sleep


class ServicePollForTokenError(wandb.Error):
    """Failed to discover how to connect to the service."""


def poll_for_token(
    file: pathlib.Path,
    proc: subprocess.Popen,
    *,
    timeout: float,
) -> service_token.ServiceToken:
    """Poll the 'port' file to discover how to connect to the service.

    Args:
        file: The file path that should eventually contain this information.
        proc: The process that's supposed to generate the file.
            If the process dies, this raises an error.
        timeout: A timeout in seconds after which to raise an error.

    Returns:
        A token specifying how to connect to the service process.

    Raises:
        ServicePollForTokenError: if the service process dies, a timeout
            occurs, or there's an issue reading the port file.
    """
    end_time = _MONOTONIC() + timeout

    while _MONOTONIC() < end_time:
        if (code := proc.poll()) is not None:
            raise ServicePollForTokenError(
                f"wandb-core exited with code {code}",
                context={
                    "command": proc.args,
                    "proc_out": proc.stdout.read() if proc.stdout else "",
                    "proc_err": proc.stderr.read() if proc.stderr else "",
                },
            )

        if token := _poll_once(file):
            return token

        _SLEEP(max(0, min(0.2, end_time - _MONOTONIC())))

    raise ServicePollForTokenError(
        f"Failed to read port info after {timeout} seconds.",
    )


_UNIX_NAME_RE = re.compile(r"unix=(.+)")
_TCP_PORT_RE = re.compile(r"sock=(\d+)")


def _poll_once(file: pathlib.Path) -> service_token.ServiceToken | None:
    """Try to read the port file.

    Returns:
        A connection token on success. Otherwise, returns None.

    Raises:
        ServicePollForTokenError: if the file contains no known
            connection method.
    """
    try:
        text = file.read_text()
    except OSError:
        return None

    lines = text.splitlines()
    if lines[-1] != "EOF":
        return None

    for line in lines:
        if ipc_support.SUPPORTS_UNIX and (match := _UNIX_NAME_RE.fullmatch(line)):
            return service_token.UnixServiceToken(
                parent_pid=os.getpid(),
                path=match.group(1),
            )
        elif match := _TCP_PORT_RE.fullmatch(line):
            return service_token.TCPServiceToken(
                parent_pid=os.getpid(),
                port=int(match.group(1)),
            )

    raise ServicePollForTokenError(
        f"No known connection method in {file}:\n{text}",
    )
