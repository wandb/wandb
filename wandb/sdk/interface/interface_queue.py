"""InterfaceQueue - Derived from InterfaceShared using queues to send to internal thread.

See interface.py for how interface classes relate to each other.

"""

import logging
from multiprocessing.process import BaseProcess
from typing import TYPE_CHECKING, Optional

from wandb.sdk.mailbox import Mailbox

from .interface_shared import InterfaceShared

if TYPE_CHECKING:
    from queue import Queue

    from wandb.proto import wandb_internal_pb2 as pb


logger = logging.getLogger("wandb")


class InterfaceQueue(InterfaceShared):
    def __init__(
        self,
        record_q: Optional["Queue[pb.Record]"] = None,
        result_q: Optional["Queue[pb.Result]"] = None,
        process: Optional[BaseProcess] = None,
        mailbox: Optional[Mailbox] = None,
    ) -> None:
        self.record_q = record_q
        self.result_q = result_q
        self._process = process
        super().__init__(mailbox=mailbox)

    def _publish(self, record: "pb.Record", local: Optional[bool] = None) -> None:
        if self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
        if local:
            record.control.local = local
        if self.record_q:
            self.record_q.put(record)
