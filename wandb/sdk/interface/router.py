"""Router - handle message router (base class).

Router to manage responses.

"""

import logging
import threading
import uuid
from abc import abstractmethod
from typing import TYPE_CHECKING, Dict, Optional

from ..lib import mailbox, tracelog
from .message_future import MessageFuture

if TYPE_CHECKING:
    from queue import Queue

    from wandb.proto import wandb_internal_pb2 as pb


logger = logging.getLogger("wandb")


class MessageRouterClosedError(Exception):
    """Router has been closed."""

    pass


class MessageFutureObject(MessageFuture):
    def __init__(self) -> None:
        super().__init__()

    def get(self, timeout: Optional[int] = None) -> Optional["pb.Result"]:
        is_set = self._object_ready.wait(timeout)
        if is_set and self._object:
            return self._object
        return None


class MessageRouter:
    _pending_reqs: Dict[str, MessageFutureObject]
    _request_queue: "Queue[pb.Record]"
    _response_queue: "Queue[pb.Result]"
    _mailbox: Optional[mailbox.Mailbox]

    def __init__(self, mailbox: Optional[mailbox.Mailbox] = None) -> None:
        self._mailbox = mailbox
        self._pending_reqs = {}
        self._lock = threading.Lock()

        self._join_event = threading.Event()
        self._thread = threading.Thread(target=self.message_loop)
        self._thread.name = "MsgRouterThr"
        self._thread.daemon = True
        self._thread.start()

    @abstractmethod
    def _read_message(self) -> Optional["pb.Result"]:
        raise NotImplementedError

    @abstractmethod
    def _send_message(self, record: "pb.Record") -> None:
        raise NotImplementedError

    def message_loop(self) -> None:
        while not self._join_event.is_set():
            try:
                msg = self._read_message()
            except EOFError:
                # On abnormal shutdown the queue will be destroyed underneath
                # resulting in EOFError.  message_loop needs to exit..
                logger.warning("EOFError seen in message_loop")
                break
            except MessageRouterClosedError:
                logger.warning("message_loop has been closed")
                break
            if not msg:
                continue
            self._handle_msg_rcv(msg)

    def send_and_receive(
        self, rec: "pb.Record", local: Optional[bool] = None
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
        self._join_event.set()
        self._thread.join()

    def _handle_msg_rcv(self, msg: "pb.Result") -> None:
        # deliver mailbox addressed messages to mailbox
        if self._mailbox and msg.control.mailbox_slot:
            self._mailbox.deliver(msg)
            return
        with self._lock:
            future = self._pending_reqs.pop(msg.uuid, None)
        if future is None:
            # TODO (cvp): saw this in tests, seemed benign enough to ignore, but
            # could point to other issues.
            if msg.uuid != "":
                tracelog.log_message_assert(msg)
                logger.warning(
                    "No listener found for msg with uuid %s (%s)", msg.uuid, msg
                )
            return
        future._set_object(msg)
