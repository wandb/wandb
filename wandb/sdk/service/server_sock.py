import queue
import socket
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.internal.settings_static import SettingsStatic

from ..lib import tracelog
from ..lib.sock_client import SockClient, SockClientClosedError
from .streams import StreamMux

if TYPE_CHECKING:
    from threading import Event

    from ..interface.interface_relay import InterfaceRelay


class ClientDict:
    _client_dict: Dict[str, SockClient]
    _lock: threading.Lock

    def __init__(self) -> None:
        self._client_dict = {}
        self._lock = threading.Lock()

    def get_client(self, client_id: str) -> Optional[SockClient]:
        with self._lock:
            client = self._client_dict.get(client_id)
        return client

    def add_client(self, client: SockClient) -> None:
        with self._lock:
            self._client_dict[client._sockid] = client

    def del_client(self, client: SockClient) -> None:
        with self._lock:
            del self._client_dict[client._sockid]


class SockServerInterfaceReaderThread(threading.Thread):
    _socket_client: SockClient
    _stopped: "Event"

    def __init__(
        self, clients: ClientDict, iface: "InterfaceRelay", stopped: "Event"
    ) -> None:
        self._iface = iface
        self._clients = clients
        threading.Thread.__init__(self)
        self.name = "SockSrvIntRdThr"
        self._stopped = stopped

    def run(self) -> None:
        assert self._iface.relay_q
        while not self._stopped.is_set():
            try:
                result = self._iface.relay_q.get(timeout=1)
            except queue.Empty:
                continue
            except OSError:
                # handle is closed
                break
            except ValueError:
                # queue is closed
                break
            tracelog.log_message_dequeue(result, self._iface.relay_q)
            sockid = result.control.relay_id
            assert sockid
            sock_client = self._clients.get_client(sockid)
            assert sock_client
            sresp = spb.ServerResponse()
            sresp.result_communicate.CopyFrom(result)
            sock_client.send_server_response(sresp)


class SockServerReadThread(threading.Thread):
    _sock_client: SockClient
    _mux: StreamMux
    _stopped: "Event"
    _clients: ClientDict

    def __init__(
        self, conn: socket.socket, mux: StreamMux, clients: ClientDict
    ) -> None:
        self._mux = mux
        threading.Thread.__init__(self)
        self.name = "SockSrvRdThr"
        sock_client = SockClient()
        sock_client.set_socket(conn)
        self._sock_client = sock_client
        self._stopped = mux._get_stopped_event()
        self._clients = clients

    def run(self) -> None:
        while not self._stopped.is_set():
            try:
                sreq = self._sock_client.read_server_request()
            except SockClientClosedError:
                # socket has been closed
                # TODO: shut down other threads serving this socket?
                break
            assert sreq, "read_server_request should never timeout"
            sreq_type = sreq.WhichOneof("server_request_type")
            shandler_str = "server_" + sreq_type  # type: ignore
            shandler: Callable[[spb.ServerRequest], None] = getattr(  # type: ignore
                self, shandler_str, None
            )
            assert shandler, f"unknown handle: {shandler_str}"  # type: ignore
            shandler(sreq)

    def stop(self) -> None:
        try:
            # See shutdown notes in class SocketServer for a discussion about this mechanism
            self._sock_client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock_client.close()

    def server_inform_init(self, sreq: "spb.ServerRequest") -> None:
        request = sreq.inform_init
        stream_id = request._info.stream_id
        settings = SettingsStatic(request.settings)
        self._mux.add_stream(stream_id, settings=settings)

        iface = self._mux.get_stream(stream_id).interface
        self._clients.add_client(self._sock_client)
        iface_reader_thread = SockServerInterfaceReaderThread(
            clients=self._clients,
            iface=iface,
            stopped=self._stopped,
        )
        iface_reader_thread.start()

    def server_inform_start(self, sreq: "spb.ServerRequest") -> None:
        request = sreq.inform_start
        stream_id = request._info.stream_id
        settings = SettingsStatic(request.settings)
        self._mux.update_stream(stream_id, settings=settings)
        self._mux.start_stream(stream_id)

    def server_inform_attach(self, sreq: "spb.ServerRequest") -> None:
        request = sreq.inform_attach
        stream_id = request._info.stream_id

        self._clients.add_client(self._sock_client)
        inform_attach_response = spb.ServerInformAttachResponse()
        inform_attach_response.settings.CopyFrom(
            self._mux._streams[stream_id]._settings._proto,
        )
        response = spb.ServerResponse(inform_attach_response=inform_attach_response)
        self._sock_client.send_server_response(response)
        iface = self._mux.get_stream(stream_id).interface

        assert iface

    def server_record_communicate(self, sreq: "spb.ServerRequest") -> None:
        record = sreq.record_communicate
        # encode relay information so the right socket picks up the data
        record.control.relay_id = self._sock_client._sockid
        stream_id = record._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        assert iface.record_q
        iface.record_q.put(record)

    def server_record_publish(self, sreq: "spb.ServerRequest") -> None:
        record = sreq.record_publish
        # encode relay information so the right socket picks up the data
        record.control.relay_id = self._sock_client._sockid
        stream_id = record._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        assert iface.record_q
        iface.record_q.put(record)

    def server_inform_finish(self, sreq: "spb.ServerRequest") -> None:
        request = sreq.inform_finish
        stream_id = request._info.stream_id
        self._mux.drop_stream(stream_id)

    def server_inform_teardown(self, sreq: "spb.ServerRequest") -> None:
        request = sreq.inform_teardown
        exit_code = request.exit_code
        self._mux.teardown(exit_code)


class SockAcceptThread(threading.Thread):
    _sock: socket.socket
    _mux: StreamMux
    _stopped: "Event"
    _clients: ClientDict

    def __init__(self, sock: socket.socket, mux: StreamMux) -> None:
        self._sock = sock
        self._mux = mux
        self._stopped = mux._get_stopped_event()
        threading.Thread.__init__(self)
        self.name = "SockAcceptThr"
        self._clients = ClientDict()

    def run(self) -> None:
        self._sock.listen(5)
        read_threads = []

        while not self._stopped.is_set():
            try:
                conn, addr = self._sock.accept()
            except ConnectionAbortedError:
                break
            except OSError:
                # on shutdown
                break
            sr = SockServerReadThread(conn=conn, mux=self._mux, clients=self._clients)
            sr.start()
            read_threads.append(sr)

        for rt in read_threads:
            rt.stop()


class DebugThread(threading.Thread):
    def __init__(self, mux: "StreamMux") -> None:
        threading.Thread.__init__(self)
        self.daemon = True
        self.name = "DebugThr"

    def run(self) -> None:
        while True:
            time.sleep(30)
            for thread in threading.enumerate():
                print(f"DEBUG: {thread.name}")


class SocketServer:
    _mux: StreamMux
    _address: str
    _port: int
    _sock: socket.socket

    def __init__(self, mux: Any, address: str, port: int) -> None:
        self._mux = mux
        self._address = address
        self._port = port
        # This is the server socket that we accept new connections from
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def _bind(self) -> None:
        self._sock.bind((self._address, self._port))
        self._port = self._sock.getsockname()[1]

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        self._bind()
        self._thread = SockAcceptThread(sock=self._sock, mux=self._mux)
        self._thread.start()
        # Note: Uncomment to figure out what thread is not exiting properly
        # self._dbg_thread = DebugThread(mux=self._mux)
        # self._dbg_thread.start()

    def stop(self) -> None:
        if self._sock:
            # we need to stop the SockAcceptThread
            try:
                # TODO(jhr): consider a more graceful shutdown in the future
                # socket.shutdown() is a more heavy handed approach to interrupting socket.accept()
                # in the future we might want to consider a more graceful shutdown which would involve setting
                # a threading Event and then initiating one last connection just to close down the thread
                # The advantage of the heavy handed approach is that it doesnt depend on the threads functioning
                # properly, that is, if something has gone wrong, we probably want to use this hammer to shut things down
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
