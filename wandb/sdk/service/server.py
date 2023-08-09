"""wandb server.

Start up grpc or socket transport servers.
"""

import logging
import os
import sys
from concurrent import futures
from typing import Optional

import wandb

from ..lib import tracelog
from . import _startup_debug, port_file
from .server_sock import SocketServer
from .streams import StreamMux


class WandbServer:
    _pid: Optional[int]
    _grpc_port: Optional[int]
    _sock_port: Optional[int]
    _debug: bool
    _serve_grpc: bool
    _serve_sock: bool
    _sock_server: Optional[SocketServer]
    _startup_debug_enabled: bool

    def __init__(
        self,
        grpc_port: Optional[int] = None,
        sock_port: Optional[int] = None,
        port_fname: Optional[str] = None,
        address: Optional[str] = None,
        pid: Optional[int] = None,
        debug: bool = True,
        serve_grpc: bool = False,
        serve_sock: bool = False,
    ) -> None:
        self._grpc_port = grpc_port
        self._sock_port = sock_port
        self._port_fname = port_fname
        self._address = address
        self._pid = pid
        self._debug = debug
        self._serve_grpc = serve_grpc
        self._serve_sock = serve_sock
        self._sock_server = None
        self._startup_debug_enabled = _startup_debug.is_enabled()

        if grpc_port:
            _ = wandb.util.get_module(
                "grpc",
                required="grpc port requires the grpcio library, run pip install wandb[grpc]",
            )

        if debug:
            logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    def _inform_used_ports(
        self, grpc_port: Optional[int], sock_port: Optional[int]
    ) -> None:
        if not self._port_fname:
            return
        pf = port_file.PortFile(grpc_port=grpc_port, sock_port=sock_port)
        pf.write(self._port_fname)

    def _start_grpc(self, mux: StreamMux) -> int:
        import grpc

        from wandb.proto import wandb_server_pb2_grpc as spb_grpc

        from .server_grpc import WandbServicer

        address: str = self._address or "127.0.0.1"
        port: int = self._grpc_port or 0
        pid: int = self._pid or 0
        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="GrpcPoolThr")
        )
        servicer = WandbServicer(server=server, mux=mux)
        try:
            spb_grpc.add_InternalServiceServicer_to_server(servicer, server)
            port = server.add_insecure_port(f"{address}:{port}")
            mux.set_port(port)
            mux.set_pid(pid)
            server.start()
        except KeyboardInterrupt:
            mux.cleanup()
            server.stop(0)
            raise
        except Exception:
            mux.cleanup()
            server.stop(0)
            raise
        return port

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

    def _setup_tracelog(self) -> None:
        # TODO: remove this temporary hack, need to find a better way to pass settings
        # to the server.  for now lets just look at the environment variable we need
        tracelog_mode = os.environ.get("WANDB_TRACELOG")
        if tracelog_mode:
            tracelog.enable(tracelog_mode)

    def _startup_debug_print(self, message: str) -> None:
        if not self._startup_debug_enabled:
            return
        _startup_debug.print_message(message)

    def _setup_proctitle(
        self, grpc_port: Optional[int], sock_port: Optional[int]
    ) -> None:
        # TODO: similar to _setup_tracelog, the internal_process should have
        # a better way to have access to settings.
        disable_setproctitle = os.environ.get("WANDB__DISABLE_SETPROCTITLE")
        if disable_setproctitle:
            return

        setproctitle = wandb.util.get_optional_module("setproctitle")
        if setproctitle:
            service_ver = 2
            pid = str(self._pid or 0)
            transport = "s" if sock_port else "g"
            port = grpc_port or sock_port or 0
            # this format is similar to wandb_manager token, but it's purely informative now
            # (consider unifying this in the future)
            service_id = f"{service_ver}-{pid}-{transport}-{port}"
            proc_title = f"wandb-service({service_id})"
            self._startup_debug_print("before_setproctitle")
            setproctitle.setproctitle(proc_title)
            self._startup_debug_print("after_setproctitle")

    def serve(self) -> None:
        self._setup_tracelog()
        mux = StreamMux()
        self._startup_debug_print("before_network")
        grpc_port = self._start_grpc(mux=mux) if self._serve_grpc else None
        sock_port = self._start_sock(mux=mux) if self._serve_sock else None
        self._startup_debug_print("after_network")
        self._inform_used_ports(grpc_port=grpc_port, sock_port=sock_port)
        self._startup_debug_print("after_inform")
        self._setup_proctitle(grpc_port=grpc_port, sock_port=sock_port)
        self._startup_debug_print("before_loop")
        mux.loop()
        self._stop_servers()
