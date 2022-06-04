import socket
import struct
from typing import Any, Optional
from typing import TYPE_CHECKING
import uuid

from wandb.proto import wandb_server_pb2 as spb

from . import tracelog

if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2 as pb


class SockClientClosedError(Exception):
    """Socket has been closed"""

    pass


class SockClient:
    _sock: socket.socket
    _data: bytes
    _sockid: str

    # current header is magic byte "W" followed by 4 byte length of the message
    HEADLEN = 1 + 4

    def __init__(self) -> None:
        self._data = b""
        # TODO: use safe uuid's (python3.7+) or emulate this
        self._sockid = uuid.uuid4().hex

    def connect(self, port: int) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", port))
        self._sock = s

    def close(self) -> None:
        self._sock.close()

    def shutdown(self, val: int) -> None:
        self._sock.shutdown(val)

    def set_socket(self, sock: socket.socket) -> None:
        self._sock = sock

    def _send_message(self, msg: Any) -> None:
        tracelog.log_message_send(msg, self._sockid)
        raw_size = msg.ByteSize()
        data = msg.SerializeToString()
        assert len(data) == raw_size, "invalid serialization"
        header = struct.pack("<BI", ord("W"), raw_size)
        self._sock.sendall(header + data)

    def send_server_request(self, msg: Any) -> None:
        self._send_message(msg)

    def send_server_response(self, msg: Any) -> None:
        try:
            self._send_message(msg)
        except BrokenPipeError:
            # TODO(jhr): user thread might no longer be around to receive responses to
            # things like network status poll loop, there might be a better way to quiesce
            pass

    def send_and_recv(
        self,
        *,
        inform_init: spb.ServerInformInitRequest = None,
        inform_start: spb.ServerInformStartRequest = None,
        inform_attach: spb.ServerInformAttachRequest = None,
        inform_finish: spb.ServerInformFinishRequest = None,
        inform_teardown: spb.ServerInformTeardownRequest = None,
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
        inform_init: spb.ServerInformInitRequest = None,
        inform_start: spb.ServerInformStartRequest = None,
        inform_attach: spb.ServerInformAttachRequest = None,
        inform_finish: spb.ServerInformFinishRequest = None,
        inform_teardown: spb.ServerInformTeardownRequest = None,
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
        len_data = len(self._data)
        start_offset = self.HEADLEN
        if len_data >= start_offset:
            header = self._data[:start_offset]
            fields = struct.unpack("<BI", header)
            magic, dlength = fields
            assert magic == ord("W")
            # Do we have enough data to read the full record?
            end_offset = self.HEADLEN + dlength
            if len_data >= end_offset:
                rec_data = self._data[start_offset:end_offset]
                self._data = self._data[end_offset:]
                return rec_data
        return None

    def _read_packet_bytes(self, timeout: int = None) -> Optional[bytes]:
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
                data = self._sock.recv(4096)
            except socket.timeout:
                break
            except ConnectionResetError:
                raise SockClientClosedError()
            except OSError:
                raise SockClientClosedError()
            finally:
                if timeout:
                    self._sock.settimeout(None)
            if len(data) == 0:
                # socket.recv() will return 0 bytes if socket was shutdown
                # caller will handle this condition like other connection problems
                raise SockClientClosedError()
            self._data += data
        return None

    def read_server_request(self) -> Optional[spb.ServerRequest]:
        data = self._read_packet_bytes()
        if not data:
            return None
        rec = spb.ServerRequest()
        rec.ParseFromString(data)
        tracelog.log_message_recv(rec, self._sockid)
        return rec

    def read_server_response(self, timeout: int = None) -> Optional[spb.ServerResponse]:
        data = self._read_packet_bytes(timeout=timeout)
        if not data:
            return None
        rec = spb.ServerResponse()
        rec.ParseFromString(data)
        tracelog.log_message_recv(rec, self._sockid)
        return rec
