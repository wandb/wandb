"""Reliably launch and connect to backend server process (wandb service).

Backend server process can be connected to using tcp sockets or grpc transport.
"""

import os
import platform
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from . import _startup_debug, port_file
from .service_base import ServiceInterface
from .service_sock import ServiceSockInterface

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


class _Service:
    _settings: "Settings"
    _grpc_port: Optional[int]
    _sock_port: Optional[int]
    _service_interface: ServiceInterface
    _internal_proc: Optional[subprocess.Popen]
    _use_grpc: bool
    _startup_debug_enabled: bool

    def __init__(
        self,
        settings: "Settings",
    ) -> None:
        self._settings = settings
        self._stub = None
        self._grpc_port = None
        self._sock_port = None
        self._internal_proc = None
        self._startup_debug_enabled = _startup_debug.is_enabled()

        # Temporary setting to allow use of grpc so that we can keep
        # that code from rotting during the transition
        self._use_grpc = self._settings._service_transport == "grpc"

        # current code only supports grpc or socket server implementation, in the
        # future we might be able to support both
        if self._use_grpc:
            from .service_grpc import ServiceGrpcInterface

            self._service_interface = ServiceGrpcInterface()
        else:
            self._service_interface = ServiceSockInterface()

    def _startup_debug_print(self, message: str) -> None:
        if not self._startup_debug_enabled:
            return
        _startup_debug.print_message(message)

    def _wait_for_ports(
        self, fname: str, proc: Optional[subprocess.Popen] = None
    ) -> bool:
        time_max = time.monotonic() + self._settings._service_wait
        while time.monotonic() < time_max:
            if proc and proc.poll():
                # process finished
                print("proc exited with", proc.returncode)
                return False
            if not os.path.isfile(fname):
                time.sleep(0.2)
                continue
            try:
                pf = port_file.PortFile()
                pf.read(fname)
                if not pf.is_valid:
                    time.sleep(0.2)
                    continue
                self._grpc_port = pf.grpc_port
                self._sock_port = pf.sock_port
            except Exception as e:
                print("Error:", e)
                return False
            return True
        return False

    def _launch_server(self) -> None:
        """Launch server and set ports."""

        # References for starting processes
        # - https://github.com/wandb/wandb/blob/archive/old-cli/wandb/__init__.py
        # - https://stackoverflow.com/questions/1196074/how-to-start-a-background-process-in-python
        self._startup_debug_print("launch")

        kwargs: Dict[str, Any] = dict(close_fds=True)
        # flags to handle keyboard interrupt signal that is causing a hang
        if platform.system() == "Windows":
            kwargs.update(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)  # type: ignore [attr-defined]
        else:
            kwargs.update(start_new_session=True)

        pid = os.getpid()

        with tempfile.TemporaryDirectory() as tmpdir:
            fname = os.path.join(tmpdir, f"port-{pid}.txt")

            pid_str = str(os.getpid())
            executable = self._settings._executable
            exec_cmd_list = [executable, "-m"]
            # Add coverage collection if needed
            if os.environ.get("YEA_RUN_COVERAGE") and os.environ.get("COVERAGE_RCFILE"):
                exec_cmd_list += ["coverage", "run", "-m"]
            service_args = [
                "wandb",
                "service",
                "--port-filename",
                fname,
                "--pid",
                pid_str,
                "--debug",
            ]
            if self._use_grpc:
                service_args.append("--serve-grpc")
            else:
                service_args.append("--serve-sock")
            internal_proc = subprocess.Popen(
                exec_cmd_list + service_args,
                env=os.environ,
                **kwargs,
            )
            self._startup_debug_print("wait_ports")
            ports_found = self._wait_for_ports(fname, proc=internal_proc)
            self._startup_debug_print("wait_ports_done")
            assert ports_found
            self._internal_proc = internal_proc
        self._startup_debug_print("launch_done")

    def start(self) -> None:
        self._launch_server()

    @property
    def grpc_port(self) -> Optional[int]:
        return self._grpc_port

    @property
    def sock_port(self) -> Optional[int]:
        return self._sock_port

    @property
    def service_interface(self) -> ServiceInterface:
        return self._service_interface

    def join(self) -> int:
        ret = 0
        if self._internal_proc:
            ret = self._internal_proc.wait()
        return ret
