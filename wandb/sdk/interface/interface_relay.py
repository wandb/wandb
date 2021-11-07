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
from .interface_queue import InterfaceQueue
from .message_future import MessageFuture
from .router_relay import MessageRelayRouter

if TYPE_CHECKING:
    from six.moves.queue import Queue


logger = logging.getLogger("wandb")


class InterfaceRelay(InterfaceQueue):
    relay_q: Optional["Queue[pb.Result]"]

    def __init__(
        self,
        record_q: "Queue[pb.Record]" = None,
        result_q: "Queue[pb.Result]" = None,
        relay_q: "Queue[pb.Result]" = None,
        process: BaseProcess = None,
        process_check: bool = True,
    ) -> None:
        self.relay_q = relay_q
        super(InterfaceRelay, self).__init__(
            record_q=record_q,
            result_q=result_q,
            process=process,
            process_check=process_check,
        )

    def _init_router(self) -> None:
        if self.record_q and self.result_q and self.relay_q:
            self._router = MessageRelayRouter(
                self.record_q, self.result_q, self.relay_q
            )
