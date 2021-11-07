import socket
import struct
import threading
import time
from typing import Any
from six.moves import queue

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb

from ..lib.sock_client import SockClient
from .streams import StreamMux, _dict_from_pbmap


class SockServerInterfaceReaderThread(threading.Thread):
    def __init__(self, sock_client: socket.socket, iface: Any) -> None:
        self._iface = iface
        self._sock_client = sock_client
        threading.Thread.__init__(self)

    def run(self):
        while True:
            try:
                result = self._iface.relay_q.get(timeout=1)
            except queue.Empty:
                continue
            sresp = spb.ServerResponse()
            sresp.result_communicate.CopyFrom(result)
            self._sock_client.send_server_response(sresp)


class SockServerReadThread(threading.Thread):
    _sock_client: SockClient
    _mux: StreamMux

    def __init__(self, conn: socket.socket, mux: StreamMux) -> None:
        threading.Thread.__init__(self)
        sock_client = SockClient()
        sock_client.set_socket(conn)
        self._sock_client = sock_client
        self._mux = mux

    def run(self):
        while True:
            sreq = self._sock_client.read_server_request()
            if not sreq:
                break
            sreq_type = sreq.WhichOneof("server_request_type")
            print(f"SERVER read: {sreq_type}")
            shandler_str = "server_" + sreq_type
            shandler: Callable[[Record], None] = getattr(self, shandler_str, None)
            assert shandler, "unknown handle: {}".format(shandler_str)
            shandler(sreq)

        print("done read")

    def server_inform_init(self, sreq):
        request = sreq.inform_init
        stream_id = request._info.stream_id
        settings = _dict_from_pbmap(request._settings_map)
        self._mux.add_stream(stream_id, settings=settings)

        iface = self._mux.get_stream(stream_id).interface
        iface_reader_thread = SockServerInterfaceReaderThread(
            sock_client=self._sock_client, iface=iface
        )
        iface_reader_thread.start()

    def server_record_communicate(self, sreq):
        record = sreq.record_communicate
        # print("GOT rec", record)
        stream_id = record._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface.record_q.put(record)
        # print("GOT res", result)
        # assert result  # TODO: handle errors
        # FIXME: pack this int ServerResponse
        # sresp = spb.ServerResponse()
        # sresp.result_communicate.CopyFrom(result)
        # return sresp

    def server_record_publish(self, sreq):
        record = sreq.record_publish
        # print("GOT rec", record)
        stream_id = record._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface.record_q.put(record)

    def server_inform_finish(self, sreq):
        print("INF FIN")
        request = sreq.inform_finish
        stream_id = request._info.stream_id
        self._mux.del_stream(stream_id)

    def server_inform_teardown(self, sreq):
        request = sreq.inform_teardown
        exit_code = request.exit_code
        self._mux.teardown(exit_code)


class SockAcceptThread(threading.Thread):
    _sock: socket.socket
    _mux: StreamMux

    def __init__(self, sock: socket.socket, mux: StreamMux) -> None:
        threading.Thread.__init__(self)
        self._sock = sock
        self._mux = mux

    def run(self):
        self._sock.listen(5)
        conn, addr = self._sock.accept()
        print("GOT", type(conn))
        print("Connected by", addr)
        sr = SockServerReadThread(conn=conn, mux=self._mux)
        sr.start()


class SocketServer:
    _mux: StreamMux
    _address: str
    _port: int
    _sock: socket.socket

    def __init__(self, mux: Any, address: str, port: int) -> None:
        self._mux = mux
        self._address = address
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def _bind(self) -> None:
        self._sock.bind((self._address, self._port))
        self._port = self._sock.getsockname()[1]

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        self._bind()
        print(f"Running at port: {self.port}")
        self._thread = SockAcceptThread(sock=self._sock, mux=self._mux)
        self._thread.start()
