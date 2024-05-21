import socket
import struct
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any, List, Optional

from wandb.proto import wandb_server_pb2 as spb

from . import tracelog

if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2 as pb


class SockClientClosedError(Exception):
    """Socket has been closed."""

    pass


class SockBuffer:
    _buf_list: List[bytes]
    _buf_lengths: List[int]
    _buf_total: int

    def __init__(self) -> None:
        self._buf_list = []
        self._buf_lengths = []
        self._buf_total = 0

    @property
    def length(self) -> int:
        return self._buf_total

    def _get(self, start: int, end: int, peek: bool = False) -> bytes:
        index: Optional[int] = None
        buffers = []
        need = end

        # compute buffers needed
        for i, (buf_len, buf_data) in enumerate(zip(self._buf_lengths, self._buf_list)):
            buffers.append(buf_data[:need] if need < buf_len else buf_data)
            if need <= buf_len:
                index = i
                break
            need -= buf_len

        # buffer not large enough, caller should have made sure there was enough data
        if index is None:
            raise IndexError("SockBuffer index out of range")

        # advance buffer internals if we are not peeking into the data
        if not peek:
            self._buf_total -= end
            if need < buf_len:
                # update partially used buffer list
                self._buf_list = self._buf_list[index:]
                self._buf_lengths = self._buf_lengths[index:]
                self._buf_list[0] = self._buf_list[0][need:]
                self._buf_lengths[0] -= need
            else:
                # update fully used buffer list
                self._buf_list = self._buf_list[index + 1 :]
                self._buf_lengths = self._buf_lengths[index + 1 :]

        return b"".join(buffers)[start:end]

    def get(self, start: int, end: int) -> bytes:
        return self._get(start, end)

    def peek(self, start: int, end: int) -> bytes:
        return self._get(start, end, peek=True)

    def put(self, data: bytes, data_len: int) -> None:
        self._buf_list.append(data)
        self._buf_lengths.append(data_len)
        self._buf_total += data_len


class SockClient:
    _sock: socket.socket
    _sockid: str
    _retry_delay: float
    _lock: "threading.Lock"
    _bufsize: int
    _buffer: SockBuffer

    # current header is magic byte "W" followed by 4 byte length of the message
    HEADLEN = 1 + 4

    def __init__(self) -> None:
        # TODO: use safe uuid's (python3.7+) or emulate this
        self._sockid = uuid.uuid4().hex
        self._retry_delay = 0.1
        self._lock = threading.Lock()
        self._bufsize = 4096
        self._buffer = SockBuffer()

    def connect(self, port: int) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", port))
        self._sock = s
        self._detect_bufsize()

    def _detect_bufsize(self) -> None:
        sndbuf_size = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
        rcvbuf_size = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        self._bufsize = min(sndbuf_size, rcvbuf_size, 65536)

    def close(self) -> None:
        self._sock.close()

    def shutdown(self, val: int) -> None:
        self._sock.shutdown(val)

    def set_socket(self, sock: socket.socket) -> None:
        self._sock = sock
        self._detect_bufsize()

    def _sendall_with_error_handle(self, data: bytes) -> None:
        # This is a helper function for sending data in a retry fashion.
        # Similar to the sendall() function in the socket module, but with
        # an error handling in case of timeout.
        total_sent = 0
        total_data = len(data)
        while total_sent < total_data:
            start_time = time.monotonic()
            try:
                sent = self._sock.send(data)
                # sent equal to 0 indicates a closed socket
                if sent == 0:
                    raise SockClientClosedError("socket connection broken")
                total_sent += sent
                # truncate our data to save memory
                data = data[sent:]
            # we handle the timeout case for the cases when timeout is set
            # on a system level by another application
            except socket.timeout:
                # adding sleep to avoid tight loop
                delta_time = time.monotonic() - start_time
                if delta_time < self._retry_delay:
                    time.sleep(self._retry_delay - delta_time)

    def _send_message(self, msg: Any) -> None:
        tracelog.log_message_send(msg, self._sockid)
        raw_size = msg.ByteSize()
        data = msg.SerializeToString()
        assert len(data) == raw_size, "invalid serialization"
        header = struct.pack("<BI", ord("W"), raw_size)
        with self._lock:
            self._sendall_with_error_handle(header + data)

    def send_server_request(self, msg: Any) -> None:
        self._send_message(msg)

    def send_server_response(self, msg: Any) -> None:
        try:
            self._send_message(msg)
        except BrokenPipeError:
            # TODO(jhr): user thread might no longer be around to receive responses to
            #  things like network status poll loop, there might be a better way to quiesce
            pass

    def send_and_recv(
        self,
        *,
        inform_init: Optional[spb.ServerInformInitRequest] = None,
        inform_start: Optional[spb.ServerInformStartRequest] = None,
        inform_attach: Optional[spb.ServerInformAttachRequest] = None,
        inform_finish: Optional[spb.ServerInformFinishRequest] = None,
        inform_teardown: Optional[spb.ServerInformTeardownRequest] = None,
    ) -> spb.ServerResponse:
        self.send(
            inform_init=inform_init,
            inform_start=inform_start,
            inform_attach=inform_attach,
            inform_finish=inform_finish,
            inform_teardown=inform_teardown,
        )
        # TODO: this solution is fragile, but for checking attach
        # it should be relatively stable.
        # This pass would be solved as part of the fix in https://wandb.atlassian.net/browse/WB-8709
        response = self.read_server_response(timeout=1)
        if response is None:
            raise Exception("No response")
        return response

    def send(
        self,
        *,
        inform_init: Optional[spb.ServerInformInitRequest] = None,
        inform_start: Optional[spb.ServerInformStartRequest] = None,
        inform_attach: Optional[spb.ServerInformAttachRequest] = None,
        inform_finish: Optional[spb.ServerInformFinishRequest] = None,
        inform_teardown: Optional[spb.ServerInformTeardownRequest] = None,
    ) -> None:
        server_req = spb.ServerRequest()
        if inform_init:
            server_req.inform_init.CopyFrom(inform_init)
        elif inform_start:
            server_req.inform_start.CopyFrom(inform_start)
        elif inform_attach:
            server_req.inform_attach.CopyFrom(inform_attach)
        elif inform_finish:
            server_req.inform_finish.CopyFrom(inform_finish)
        elif inform_teardown:
            server_req.inform_teardown.CopyFrom(inform_teardown)
        else:
            raise Exception("unmatched")
        self.send_server_request(server_req)

    def send_record_communicate(self, record: "pb.Record") -> None:
        server_req = spb.ServerRequest()
        server_req.record_communicate.CopyFrom(record)
        self.send_server_request(server_req)

    def send_record_publish(self, record: "pb.Record") -> None:
        server_req = spb.ServerRequest()
        server_req.record_publish.CopyFrom(record)
        self.send_server_request(server_req)

    def _extract_packet_bytes(self) -> Optional[bytes]:
        # Do we have enough data to read the header?
        start_offset = self.HEADLEN
        if self._buffer.length >= start_offset:
            header = self._buffer.peek(0, start_offset)
            fields = struct.unpack("<BI", header)
            magic, dlength = fields
            assert magic == ord("W")
            # Do we have enough data to read the full record?
            end_offset = self.HEADLEN + dlength
            if self._buffer.length >= end_offset:
                rec_data = self._buffer.get(start_offset, end_offset)
                return rec_data
        return None

    def _read_packet_bytes(self, timeout: Optional[int] = None) -> Optional[bytes]:
        """Read full message from socket.

        Args:
            timeout: number of seconds to wait on socket data.

        Raises:
            SockClientClosedError: socket has been closed.
        """
        while True:
            rec = self._extract_packet_bytes()
            if rec:
                return rec

            if timeout:
                self._sock.settimeout(timeout)
            try:
                data = self._sock.recv(self._bufsize)
            except socket.timeout:
                break
            except ConnectionResetError:
                raise SockClientClosedError
            except OSError:
                raise SockClientClosedError
            finally:
                if timeout:
                    self._sock.settimeout(None)
            data_len = len(data)
            if data_len == 0:
                # socket.recv() will return 0 bytes if socket was shutdown
                # caller will handle this condition like other connection problems
                raise SockClientClosedError
            self._buffer.put(data, data_len)
        return None

    def read_server_request(self) -> Optional[spb.ServerRequest]:
        data = self._read_packet_bytes()
        if not data:
            return None
        rec = spb.ServerRequest()
        rec.ParseFromString(data)
        tracelog.log_message_recv(rec, self._sockid)
        return rec

    def read_server_response(
        self, timeout: Optional[int] = None
    ) -> Optional[spb.ServerResponse]:
        data = self._read_packet_bytes(timeout=timeout)
        if not data:
            return None
        rec = spb.ServerResponse()
        rec.ParseFromString(data)
        tracelog.log_message_recv(rec, self._sockid)
        return rec
