from __future__ import annotations

import logging
from multiprocessing.process import BaseProcess
from typing import TYPE_CHECKING

from typing_extensions import override

from .interface_shared import InterfaceShared

if TYPE_CHECKING:
    from queue import Queue

    from wandb.proto import wandb_internal_pb2 as pb
    from wandb.sdk.mailbox.mailbox_handle import MailboxHandle


logger = logging.getLogger("wandb")


class InterfaceQueue(InterfaceShared):
    """Legacy implementation of InterfaceShared.

    This was used by legacy-service to pass messages back to itself before
    the existence of wandb-core. It may be removed once legacy-service is
    completely removed (including its use in `wandb sync`).

    Since it was used by the internal service, it does not implement
    the "deliver" methods, which are only used in the client.
    """

    def __init__(
        self,
        record_q: Queue[pb.Record] | None = None,
        result_q: Queue[pb.Result] | None = None,
        process: BaseProcess | None = None,
    ) -> None:
        self.record_q = record_q
        self.result_q = result_q
        self._process = process
        super().__init__()

    @override
    def _publish(self, record: pb.Record, *, nowait: bool = False) -> None:
        if self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
        if self.record_q:
            self.record_q.put(record)

    @override
    async def deliver_async(
        self,
        record: pb.Record,
    ) -> MailboxHandle[pb.Result]:
        raise NotImplementedError

    @override
    def _deliver(self, record: pb.Record) -> MailboxHandle[pb.Result]:
        raise NotImplementedError
