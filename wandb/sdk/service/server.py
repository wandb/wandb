"""wandb server.

Start up socket transport servers.
"""

import logging
import os
import sys
from typing import Optional

import wandb

from . import _startup_debug, port_file
from .server_sock import SocketServer
from .streams import StreamMux


class WandbServer:
    _pid: Optional[int]
    _sock_port: Optional[int]
    _debug: bool
    _sock_server: Optional[SocketServer]
    _startup_debug_enabled: bool

    def __init__(
        self,
        sock_port: Optional[int] = None,
        port_fname: Optional[str] = None,
        address: Optional[str] = None,
        pid: Optional[int] = None,
        debug: bool = True,
    ) -> None:
        self._sock_port = sock_port
        self._port_fname = port_fname
        self._address = address
        self._pid = pid
        self._debug = debug
        self._sock_server = None
        self._startup_debug_enabled = _startup_debug.is_enabled()

        if debug:
            logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    def _inform_used_ports(self, sock_port: Optional[int]) -> None:
        if not self._port_fname:
            return
        pf = port_file.PortFile(sock_port=sock_port)
        pf.write(self._port_fname)

    def _start_sock(self, mux: StreamMux) -> int:
        address: str = self._address or "127.0.0.1"
        port: int = self._sock_port or 0
        self._sock_server = SocketServer(mux=mux, address=address, port=port)
        try:
            self._sock_server.start()
            port = self._sock_server.port
            if self._pid:
                mux.set_pid(self._pid)
        except KeyboardInterrupt:
            mux.cleanup()
            raise
        except Exception:
            mux.cleanup()
            raise
        return port

    def _stop_servers(self) -> None:
        if self._sock_server:
            self._sock_server.stop()

    def _startup_debug_print(self, message: str) -> None:
        if not self._startup_debug_enabled:
            return
        _startup_debug.print_message(message)

    def _setup_proctitle(self, sock_port: Optional[int]) -> None:
        # TODO: the internal_process should have a better way to have access to
        # settings.
        disable_setproctitle = os.environ.get("WANDB_X_DISABLE_SETPROCTITLE")
        if disable_setproctitle:
            return

        setproctitle = wandb.util.get_optional_module("setproctitle")
        if setproctitle:
            service_ver = 2
            pid = str(self._pid or 0)
            transport = "s" if sock_port else "g"
            port = sock_port or 0
            # this format is similar to the service token, but it's purely informative now
            # (consider unifying this in the future)
            service_id = f"{service_ver}-{pid}-{transport}-{port}"
            proc_title = f"wandb-service({service_id})"
            self._startup_debug_print("before_setproctitle")
            setproctitle.setproctitle(proc_title)
            self._startup_debug_print("after_setproctitle")

    def serve(self) -> None:
        mux = StreamMux()
        self._startup_debug_print("before_network")
        sock_port = self._start_sock(mux=mux)
        self._startup_debug_print("after_network")
        self._inform_used_ports(sock_port=sock_port)
        self._startup_debug_print("after_inform")
        self._setup_proctitle(sock_port=sock_port)
        self._startup_debug_print("before_loop")
        mux.loop()
        self._stop_servers()
