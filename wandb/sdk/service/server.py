"""wandb server.

Start up grpc or socket transport servers.
"""

from concurrent import futures
import logging
import os
import sys
from typing import Optional

import wandb

from . import port_file
from .server_sock import SocketServer
from .streams import StreamMux
from ..lib import tracelog


class WandbServer:
    _pid: Optional[int]
    _grpc_port: Optional[int]
    _sock_port: Optional[int]
    _debug: bool
    _serve_grpc: bool
    _serve_sock: bool
    _sock_server: Optional[SocketServer]

    def __init__(
        self,
        grpc_port: int = None,
        sock_port: int = None,
        port_fname: str = None,
        address: str = None,
        pid: int = None,
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
        from .server_grpc import WandbServicer
        import grpc
        from wandb.proto import wandb_server_pb2_grpc as spb_grpc

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

    def serve(self) -> None:
        self._setup_tracelog()
        mux = StreamMux()
        grpc_port = self._start_grpc(mux=mux) if self._serve_grpc else None
        sock_port = self._start_sock(mux=mux) if self._serve_sock else None
        self._inform_used_ports(grpc_port=grpc_port, sock_port=sock_port)
        setproctitle = wandb.util.get_optional_module("setproctitle")
        if setproctitle:
            service_ver = 2
            pid = str(self._pid or 0)
            transport = "s" if sock_port else "g"
            port = grpc_port or sock_port or 0
            # this format is similar to wandb_manager token but it purely informative now
            # (consider unifying this in the future)
            service_id = f"{service_ver}-{pid}-{transport}-{port}"
            proc_title = f"wandb-service({service_id})"
            setproctitle.setproctitle(proc_title)
        mux.loop()
        self._stop_servers()
