"""Router - handle message router (sock)

Router to manage responses from a socket client.

"""

from typing import Optional
from typing import TYPE_CHECKING

from .router import MessageRouter, MessageRouterClosedError
from ..lib.sock_client import SockClient, SockClientClosedError

if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2 as pb


class MessageSockRouter(MessageRouter):
    _sock_client: SockClient

    def __init__(self, sock_client: SockClient) -> None:
        self._sock_client = sock_client
        super().__init__()

    def _read_message(self) -> "Optional[pb.Result]":
        try:
            resp = self._sock_client.read_server_response(timeout=1)
        except SockClientClosedError:
            raise MessageRouterClosedError
        if not resp:
            return None
        msg = resp.result_communicate
        return msg

    def _send_message(self, record: "pb.Record") -> None:
        self._sock_client.send_record_communicate(record)
