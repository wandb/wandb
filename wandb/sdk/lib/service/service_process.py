"""Module for starting up the service process (wandb-core)."""

from __future__ import annotations

import os
import pathlib
import platform
import subprocess
import tempfile
from typing import TYPE_CHECKING

from wandb import _sentry
from wandb.env import core_debug, dcgm_profiling_enabled, error_reporting_enabled
from wandb.errors import WandbCoreNotAvailableError
from wandb.sdk.lib.service import ipc_support
from wandb.util import get_core_path

from . import service_port_file, service_token

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


def start(settings: Settings) -> ServiceProcess:
    """Start the internal service process.

    Returns:
        A handle to the process.
    """
    _sentry.configure_scope(tags=dict(settings), process_context="service")

    try:
        return _launch_server(settings)
    except Exception as e:
        _sentry.reraise(e)


class ServiceProcess:
    """A handle to a process running the internal service."""

    def __init__(
        self,
        *,
        connection_token: service_token.ServiceToken,
        process: subprocess.Popen,
    ) -> None:
        self._token = connection_token
        self._process = process

    @property
    def token(self) -> service_token.ServiceToken:
        """A token for connecting to the process."""
        return self._token

    def join(self) -> int:
        """Wait for the process to end and return its exit code."""
        return self._process.wait()


def _launch_server(settings: Settings) -> ServiceProcess:
    """Launch server and set ports."""
    if platform.system() == "Windows":
        creationflags: int = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        start_new_session = False
    else:
        creationflags = 0
        start_new_session = True

    pid = str(os.getpid())

    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = pathlib.Path(tmpdir, f"port-{pid}.txt")
        service_args: list[str] = []

        try:
            core_path = get_core_path()
        except WandbCoreNotAvailableError as e:
            _sentry.reraise(e)

        service_args.extend([core_path])

        if not error_reporting_enabled():
            service_args.append("--no-observability")

        if core_debug(default="False"):
            service_args.extend(["--log-level", "-4"])

        if dcgm_profiling_enabled():
            service_args.append("--enable-dcgm-profiling")

        service_args.extend(["--port-filename", str(port_file)])
        service_args.extend(["--pid", pid])

        if not ipc_support.SUPPORTS_UNIX:
            service_args.append("--listen-on-localhost")

        proc = subprocess.Popen(
            service_args,
            env=os.environ,
            close_fds=True,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )

        token = service_port_file.poll_for_token(
            port_file,
            proc,
            timeout=settings.x_service_wait,
        )

        return ServiceProcess(connection_token=token, process=proc)
