"""Reliably launch and connect to backend server process (wandb-core).

Backend server process can be connected to using tcp sockets transport.
"""

import os
import platform
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from wandb import _sentry
from wandb.env import core_debug, dcgm_profiling_enabled, error_reporting_enabled
from wandb.errors import Error, WandbCoreNotAvailableError
from wandb.util import get_core_path

from . import port_file

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


class ServiceStartProcessError(Error):
    """Raised when a known error occurs when launching wandb service."""


class ServiceStartTimeoutError(Error):
    """Raised when service start times out."""


class ServiceStartPortError(Error):
    """Raised when service start fails to find a port."""


class _Service:
    _settings: "Settings"
    _sock_port: Optional[int]
    _internal_proc: Optional[subprocess.Popen]

    def __init__(
        self,
        settings: "Settings",
    ) -> None:
        self._settings = settings
        self._stub = None
        self._sock_port = None
        self._internal_proc = None

        _sentry.configure_scope(tags=dict(settings), process_context="service")

    def _wait_for_ports(
        self, fname: str, proc: Optional[subprocess.Popen] = None
    ) -> None:
        """Wait for the service to write the port file and then read it.

        Args:
            fname: The path to the port file.
            proc: The process to wait for.

        Raises:
            ServiceStartTimeoutError: If the service takes too long to start.
            ServiceStartPortError: If the service writes an invalid port file or unable to read it.
            ServiceStartProcessError: If the service process exits unexpectedly.

        """
        time_max = time.monotonic() + self._settings.x_service_wait
        while time.monotonic() < time_max:
            if proc and proc.poll():
                context = dict(
                    command=proc.args,
                    proc_out=proc.stdout.read() if proc.stdout else "",
                    proc_err=proc.stderr.read() if proc.stderr else "",
                )
                raise ServiceStartProcessError(
                    f"The wandb-core process exited with {proc.returncode}.",
                    context=context,
                )
            if not os.path.isfile(fname):
                time.sleep(0.2)
                continue
            try:
                pf = port_file.PortFile()
                pf.read(fname)
                if not pf.is_valid:
                    time.sleep(0.2)
                    continue
                self._sock_port = pf.sock_port
            except Exception as e:
                # todo: point at the docs. this could be due to a number of reasons,
                #  for example, being unable to write to the port file etc.
                raise ServiceStartPortError(
                    f"Failed to allocate port for wandb service: {e}."
                )
            return
        raise ServiceStartTimeoutError(
            "Timed out waiting for wandb service to start after "
            f"{self._settings.x_service_wait} seconds. "
            "Try increasing the timeout with the `_service_wait` setting."
        )

    def _launch_server(self) -> None:
        """Launch server and set ports."""
        # References for starting processes
        # - https://github.com/wandb/wandb/blob/archive/old-cli/wandb/__init__.py
        # - https://stackoverflow.com/questions/1196074/how-to-start-a-background-process-in-python
        kwargs: Dict[str, Any] = dict(close_fds=True)
        # flags to handle keyboard interrupt signal that is causing a hang
        if platform.system() == "Windows":
            kwargs.update(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)  # type: ignore [attr-defined]
        else:
            kwargs.update(start_new_session=True)

        pid = str(os.getpid())

        with tempfile.TemporaryDirectory() as tmpdir:
            fname = os.path.join(tmpdir, f"port-{pid}.txt")

            service_args = []

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

            service_args += [
                "--port-filename",
                fname,
                "--pid",
                pid,
            ]

            try:
                internal_proc = subprocess.Popen(service_args, env=os.environ, **kwargs)
            except Exception as e:
                _sentry.reraise(e)

            try:
                self._wait_for_ports(fname, proc=internal_proc)
            except Exception as e:
                _sentry.reraise(e)
            self._internal_proc = internal_proc

    def start(self) -> None:
        self._launch_server()

    @property
    def sock_port(self) -> Optional[int]:
        return self._sock_port

    def join(self) -> int:
        ret = 0
        if self._internal_proc:
            ret = self._internal_proc.wait()
        return ret
