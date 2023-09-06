"""InterfaceQueue - Derived from InterfaceShared using queues to send to internal thread.

See interface.py for how interface classes relate to each other.

"""

import logging
from multiprocessing.process import BaseProcess
from typing import TYPE_CHECKING, Optional

from ..lib import tracelog
from ..lib.mailbox import Mailbox
from .interface_shared import InterfaceShared
from .router_queue import MessageQueueRouter

if TYPE_CHECKING:
    from queue import Queue

    from wandb.proto import wandb_internal_pb2 as pb


logger = logging.getLogger("wandb")


class InterfaceQueue(InterfaceShared):
    record_q: Optional["Queue[pb.Record]"]
    result_q: Optional["Queue[pb.Result]"]
    _mailbox: Optional[Mailbox]

    def __init__(
        self,
        record_q: Optional["Queue[pb.Record]"] = None,
        result_q: Optional["Queue[pb.Result]"] = None,
        process: Optional[BaseProcess] = None,
        process_check: bool = True,
        mailbox: Optional[Mailbox] = None,
    ) -> None:
        self.record_q = record_q
        self.result_q = result_q
        if self.record_q:
            tracelog.annotate_queue(self.record_q, "record_q")
        if self.result_q:
            tracelog.annotate_queue(self.result_q, "result_q")
        super().__init__(process=process, process_check=process_check, mailbox=mailbox)

    def _init_router(self) -> None:
        if self.record_q and self.result_q:
            self._router = MessageQueueRouter(
                self.record_q, self.result_q, mailbox=self._mailbox
            )

    def _publish(self, record: "pb.Record", local: Optional[bool] = None) -> None:
        if self._process_check and self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
        if local:
            record.control.local = local
        if self.record_q:
            tracelog.log_message_queue(record, self.record_q)
            self.record_q.put(record)
