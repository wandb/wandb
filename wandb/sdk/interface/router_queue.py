"""Router - handle message router (queue).

Router to manage responses from a queue.

"""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.mailbox import Mailbox

from .router import MessageRouter

if TYPE_CHECKING:
    from queue import Queue


class MessageQueueRouter(MessageRouter):
    _request_queue: Queue[pb.Record]
    _response_queue: Queue[pb.Result]

    def __init__(
        self,
        request_queue: Queue[pb.Record],
        response_queue: Queue[pb.Result],
        mailbox: Mailbox | None = None,
    ) -> None:
        self._request_queue = request_queue
        self._response_queue = response_queue
        super().__init__(mailbox=mailbox)

    def _read_message(self) -> pb.Result | None:
        try:
            msg = self._response_queue.get(timeout=1)
        except queue.Empty:
            return None
        return msg

    def _send_message(self, record: pb.Record) -> None:
        self._request_queue.put(record)
