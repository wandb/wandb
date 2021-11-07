"""Router - handle message router (queue)

Router to manage responses from a queue.

"""

from typing import TYPE_CHECKING
from six.moves import queue

from .router import MessageRouter

if TYPE_CHECKING:
    from six.moves.queue import Queue


class MessageQueueRouter(MessageRouter):
    _request_queue: "Queue[pb.Record]"
    _response_queue: "Queue[pb.Result]"

    def __init__(
        self, request_queue: "Queue[pb.Record]", response_queue: "Queue[pb.Result]"
    ) -> None:
        self._request_queue = request_queue
        self._response_queue = response_queue
        super(MessageQueueRouter, self).__init__()

    def _read_message(self) -> "Optional[pb.Result]":
        try:
            msg = self._response_queue.get(timeout=1)
        except queue.Empty:
            return None
        return msg

    def _send_message(self, record: "pb.Record") -> None:
        self._request_queue.put(record)
