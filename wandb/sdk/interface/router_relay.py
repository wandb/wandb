"""Router - handle message router (relay)

Router to manage responses from a queue with relay.

"""

from typing import TYPE_CHECKING

from .router_queue import MessageQueueRouter
from ..lib import tracelog

if TYPE_CHECKING:
    from queue import Queue
    from wandb.proto import wandb_internal_pb2 as pb


class MessageRelayRouter(MessageQueueRouter):
    _relay_queue: "Queue[pb.Result]"

    def __init__(
        self,
        request_queue: "Queue[pb.Record]",
        response_queue: "Queue[pb.Result]",
        relay_queue: "Queue[pb.Result]",
    ) -> None:
        self._relay_queue = relay_queue
        super().__init__(request_queue=request_queue, response_queue=response_queue)

    def _handle_msg_rcv(self, msg: "pb.Result") -> None:
        if msg.control.relay_id:
            tracelog.log_message_queue(msg, self._relay_queue)
            self._relay_queue.put(msg)
            return
        super()._handle_msg_rcv(msg)
