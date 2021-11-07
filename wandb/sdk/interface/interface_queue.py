"""InterfaceQueue - Derived from InterfaceShared using queues to send to internal thread

See interface.py for how interface classes relate to each other.

"""

import logging
from multiprocessing.process import BaseProcess
from typing import Any, Optional
from typing import cast
from typing import TYPE_CHECKING

import six
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.util import (
    json_dumps_safer,
    json_friendly,
)

from . import summary_record as sr
from .interface_shared import InterfaceShared
from .message_future import MessageFuture
from .router_queue import MessageQueueRouter

if TYPE_CHECKING:
    from six.moves.queue import Queue


logger = logging.getLogger("wandb")


class InterfaceQueue(InterfaceShared):
    record_q: Optional["Queue[pb.Record]"]
    result_q: Optional["Queue[pb.Result]"]

    def __init__(
        self,
        record_q: "Queue[pb.Record]" = None,
        result_q: "Queue[pb.Result]" = None,
        process: BaseProcess = None,
        process_check: bool = True,
    ) -> None:
        self.record_q = record_q
        self.result_q = result_q
        super(InterfaceQueue, self).__init__(
            process=process, process_check=process_check
        )

    def _init_router(self) -> None:
        if self.record_q and self.result_q:
            self._router = MessageQueueRouter(self.record_q, self.result_q)

    def _publish(self, record: pb.Record, local: bool = None) -> None:
        if self._process_check and self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
        if local:
            record.control.local = local
        if self.record_q:
            self.record_q.put(record)
