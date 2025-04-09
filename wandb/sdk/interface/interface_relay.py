"""InterfaceRelay - Derived from InterfaceQueue using RelayRouter to preserve uuid req/resp.

See interface.py for how interface classes relate to each other.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.mailbox import Mailbox

from .interface_queue import InterfaceQueue

if TYPE_CHECKING:
    from queue import Queue


logger = logging.getLogger("wandb")


class InterfaceRelay(InterfaceQueue):
    _mailbox: Mailbox

    def __init__(
        self,
        mailbox: Mailbox,
        record_q: Queue[pb.Record],
        result_q: Queue[pb.Result],
        relay_q: Queue[pb.Result],
    ) -> None:
        self.relay_q = relay_q
        super().__init__(
            record_q=record_q,
            result_q=result_q,
            mailbox=mailbox,
        )
