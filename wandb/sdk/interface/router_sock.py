"""Router - handle message router (sock).

Router to manage responses from a socket client.

"""

from __future__ import annotations

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib.sock_client import SockClient, SockClientClosedError
from wandb.sdk.mailbox import Mailbox

from .router import MessageRouter, MessageRouterClosedError


class MessageSockRouter(MessageRouter):
    _sock_client: SockClient
    _mailbox: Mailbox

    def __init__(self, sock_client: SockClient, mailbox: Mailbox) -> None:
        self._sock_client = sock_client
        super().__init__(mailbox=mailbox)

    def _read_message(self) -> spb.ServerResponse | None:
        try:
            return self._sock_client.read_server_response(timeout=1)
        except SockClientClosedError as e:
            raise MessageRouterClosedError from e

    def _send_message(self, record: pb.Record) -> None:
        self._sock_client.send_record_communicate(record)
