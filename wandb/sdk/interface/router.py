"""Router - handle message router (base class)

Router to manage responses.

"""

from abc import abstractmethod
import logging
import threading
from typing import Dict, Optional
from typing import TYPE_CHECKING
import uuid

from six.moves import queue
from wandb.proto import wandb_internal_pb2 as pb

from .message_future import MessageFuture

if TYPE_CHECKING:
    from six.moves.queue import Queue


logger = logging.getLogger("wandb")


class MessageFutureObject(MessageFuture):
    def __init__(self) -> None:
        super(MessageFutureObject, self).__init__()

    def get(self, timeout: int = None) -> Optional[pb.Result]:
        is_set = self._object_ready.wait(timeout)
        if is_set and self._object:
            return self._object
        return None


class MessageRouter(object):
    _pending_reqs: Dict[str, MessageFutureObject]
    _request_queue: "Queue[pb.Record]"
    _response_queue: "Queue[pb.Result]"

    def __init__(self) -> None:
        self._pending_reqs = {}
        self._lock = threading.Lock()

        self._join_event = threading.Event()
        self._thread = threading.Thread(target=self.message_loop)
        self._thread.daemon = True
        self._thread.start()

    @abstractmethod
    def _read_message(self) -> "Optional[pb.Result]":
        raise NotImplementedError

    @abstractmethod
    def _send_message(self, record: "pb.Record") -> None:
        raise NotImplementedError

    def message_loop(self) -> None:
        while not self._join_event.is_set():
            msg = self._read_message()
            if not msg:
                continue
            self._handle_msg_rcv(msg)

    def send_and_receive(
        self, rec: pb.Record, local: Optional[bool] = None
    ) -> MessageFuture:
        rec.control.req_resp = True
        if local:
            rec.control.local = local
        rec.uuid = uuid.uuid4().hex
        future = MessageFutureObject()
        with self._lock:
            self._pending_reqs[rec.uuid] = future

        self._send_message(rec)

        return future

    def join(self) -> None:
        print("RBASEJ1")
        self._join_event.set()
        print("RBASEJ2")
        self._thread.join()
        print("RBASEJ3")

    def _handle_msg_rcv(self, msg: pb.Result) -> None:
        with self._lock:
            future = self._pending_reqs.pop(msg.uuid, None)
        if future is None:
            # TODO (cvp): saw this in tests, seemed benign enough to ignore, but
            # could point to other issues.
            if msg.uuid != "":
                logger.warning(
                    "No listener found for msg with uuid %s (%s)", msg.uuid, msg
                )
            return
        future._set_object(msg)
