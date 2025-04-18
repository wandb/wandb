"""Router - handle message router (relay).

Router to manage responses from a queue with relay.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.mailbox import Mailbox

from .router_queue import MessageQueueRouter

if TYPE_CHECKING:
    from queue import Queue


class MessageRelayRouter(MessageQueueRouter):
    _relay_queue: Queue[pb.Result]

    def __init__(
        self,
        request_queue: Queue[pb.Record],
        response_queue: Queue[pb.Result],
        relay_queue: Queue[pb.Result],
        mailbox: Mailbox,
    ) -> None:
        self._relay_queue = relay_queue
        super().__init__(
            request_queue=request_queue,
            response_queue=response_queue,
            mailbox=mailbox,
        )

    def _handle_msg_rcv(self, msg: pb.Result | spb.ServerResponse) -> None:
        if isinstance(msg, pb.Result):
            relay_msg = msg
        else:
            relay_msg = msg.result_communicate

        # This is legacy-service logic for returning responses to the client.
        # A different thread reads the "relay queue" and writes responses on
        # the socket.
        if relay_msg.control.relay_id:
            self._relay_queue.put(relay_msg)
        else:
            super()._handle_msg_rcv(msg)
