"""Router - handle message router (queue)

Router to manage responses from a queue.

"""

from six.moves import queue
import socket
import time
from typing import TYPE_CHECKING

from .router import MessageRouter
from ..lib.sock_client import SockClient

if TYPE_CHECKING:
    from six.moves.queue import Queue


class MessageSockRouter(MessageRouter):
    _sock_client: SockClient

    def __init__(self, sock_client: SockClient) -> None:
        self._sock_client = sock_client
        super(MessageSockRouter, self).__init__()

    def _read_message(self) -> "Optional[pb.Result]":
        resp = self._sock_client.read_server_response(timeout=1)
        if not resp:
            return None
        msg = resp.result_communicate
        return msg

    def _send_message(self, record: "pb.Record") -> None:
        self._sock_client.send_record_communicate(record)
