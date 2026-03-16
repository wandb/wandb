"""Module for starting up the service process (wandb-core)."""

from __future__ import annotations

import os
import pathlib
import platform
import subprocess
import tempfile
from typing import TYPE_CHECKING

from wandb.analytics import get_sentry
from wandb.env import core_debug, dcgm_profiling_enabled, error_reporting_enabled
from wandb.errors import WandbCoreNotAvailableError
from wandb.sdk.lib.service import ipc_support
from wandb.util import get_core_path

from . import service_port_file, service_token

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


DEFAULT_DETACHED_IDLE_TIMEOUT = "10m"


def start(settings: Settings) -> ServiceProcess:
    """Start the internal service process.

    Returns:
        A handle to the process.
    """
    return _start(
        settings,
        detached=False,
        idle_timeout=None,
    )


def start_detached(
    settings: Settings,
    *,
    idle_timeout: str = DEFAULT_DETACHED_IDLE_TIMEOUT,
) -> ServiceProcess:
    """Start the internal service process in detached mode.

    In detached mode, the service process does not automatically exit when the
    starting process exits.

    Args:
        settings: SDK settings.
        idle_timeout: How long the service should stay alive with no connected
            clients before shutting down. This uses Go duration syntax, for
            example ``30s`` or ``10m``. Use ``0`` to disable idle shutdown.

    Returns:
        A handle to the process.
    """
    return _start(
        settings,
        detached=True,
        idle_timeout=idle_timeout,
    )


def _start(
    settings: Settings,
    *,
    detached: bool,
    idle_timeout: str | None,
) -> ServiceProcess:
    get_sentry().configure_scope(tags=dict(settings), process_context="service")

    try:
        return _launch_server(
            settings,
            detached=detached,
            idle_timeout=idle_timeout,
        )
    except Exception as e:
        get_sentry().reraise(e)


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


def _launch_server(
    settings: Settings,
    *,
    detached: bool,
    idle_timeout: str | None,
) -> ServiceProcess:
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
            get_sentry().reraise(e)

        service_args.append(core_path)

        if not error_reporting_enabled():
            service_args.append("--no-observability")

        if core_debug(default="False"):
            service_args.extend(["--log-level", "-4"])

        if dcgm_profiling_enabled():
            service_args.append("--enable-dcgm-profiling")

        service_args.extend(["--port-filename", str(port_file)])
        service_args.extend(["--pid", pid])

        if detached:
            service_args.extend(["--detached", "--idle-timeout", idle_timeout or "0"])

        if not ipc_support.SUPPORTS_UNIX:
            service_args.append("--listen-on-localhost")

        proc = subprocess.Popen(
            service_args,
            env=os.environ,
            close_fds=True,
            creationflags=creationflags,
            start_new_session=start_new_session,
            stdin=subprocess.DEVNULL if detached else None,
            stdout=subprocess.DEVNULL if detached else None,
            stderr=subprocess.DEVNULL if detached else None,
        )

        token = service_port_file.poll_for_token(
            port_file,
            proc,
            timeout=settings.x_service_wait,
        )

        return ServiceProcess(connection_token=token, process=proc)
