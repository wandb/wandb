"""Router - handle message router (base class).

Router to manage responses.

"""

from __future__ import annotations

import logging
import threading
from abc import abstractmethod
from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk import mailbox

if TYPE_CHECKING:
    from queue import Queue


logger = logging.getLogger("wandb")


class MessageRouterClosedError(Exception):
    """Router has been closed."""


class MessageRouter:
    _request_queue: Queue[pb.Record]
    _response_queue: Queue[pb.Result]
    _mailbox: mailbox.Mailbox | None

    def __init__(self, mailbox: mailbox.Mailbox | None = None) -> None:
        self._mailbox = mailbox
        self._lock = threading.Lock()

        self._join_event = threading.Event()
        self._thread = threading.Thread(target=self.message_loop)
        self._thread.name = "MsgRouterThr"
        self._thread.daemon = True
        self._thread.start()

    @abstractmethod
    def _read_message(self) -> pb.Result | spb.ServerResponse | None:
        raise NotImplementedError

    @abstractmethod
    def _send_message(self, record: pb.Record) -> None:
        raise NotImplementedError

    def message_loop(self) -> None:
        try:
            while not self._join_event.is_set():
                try:
                    msg = self._read_message()
                except EOFError:
                    # On abnormal shutdown the queue will be destroyed underneath
                    # resulting in EOFError.  message_loop needs to exit..
                    logger.warning("EOFError seen in message_loop")
                    break
                except MessageRouterClosedError as e:
                    logger.warning("message_loop has been closed", exc_info=e)
                    break
                if not msg:
                    continue
                self._handle_msg_rcv(msg)

        finally:
            if self._mailbox:
                self._mailbox.close()

    def join(self) -> None:
        self._join_event.set()
        self._thread.join()

    def _handle_msg_rcv(self, msg: pb.Result | spb.ServerResponse) -> None:
        if not self._mailbox:
            return

        if isinstance(msg, pb.Result) and msg.control.mailbox_slot:
            self._mailbox.deliver(
                spb.ServerResponse(
                    request_id=msg.control.mailbox_slot,
                    result_communicate=msg,
                )
            )
        elif isinstance(msg, spb.ServerResponse) and msg.request_id:
            self._mailbox.deliver(msg)
