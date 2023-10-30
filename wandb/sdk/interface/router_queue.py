"""Router - handle message router (queue).

Router to manage responses from a queue.

"""

import queue
from typing import TYPE_CHECKING, Optional

from ..lib import tracelog
from ..lib.mailbox import Mailbox
from .router import MessageRouter

if TYPE_CHECKING:
    from queue import Queue

    from wandb.proto import wandb_internal_pb2 as pb


class MessageQueueRouter(MessageRouter):
    _request_queue: "Queue[pb.Record]"
    _response_queue: "Queue[pb.Result]"

    def __init__(
        self,
        request_queue: "Queue[pb.Record]",
        response_queue: "Queue[pb.Result]",
        mailbox: Optional[Mailbox] = None,
    ) -> None:
        self._request_queue = request_queue
        self._response_queue = response_queue
        super().__init__(mailbox=mailbox)

    def _read_message(self) -> Optional["pb.Result"]:
        try:
            msg = self._response_queue.get(timeout=1)
        except queue.Empty:
            return None
        tracelog.log_message_dequeue(msg, self._response_queue)
        return msg

    def _send_message(self, record: "pb.Record") -> None:
        tracelog.log_message_queue(record, self._request_queue)
        self._request_queue.put(record)
