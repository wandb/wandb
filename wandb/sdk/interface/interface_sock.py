"""InterfaceSock - Derived from InterfaceShared using a socket to send to internal thread.

See interface.py for how interface classes relate to each other.

"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from wandb.sdk.mailbox import Mailbox

from ..lib.sock_client import SockClient
from .interface_shared import InterfaceShared

if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2 as pb


logger = logging.getLogger("wandb")


class InterfaceSock(InterfaceShared):
    def __init__(
        self,
        sock_client: SockClient,
        mailbox: Mailbox,
        stream_id: str,
    ) -> None:
        super().__init__(mailbox=mailbox)
        self._sock_client = sock_client
        self._stream_id = stream_id

    def _assign(self, record: Any) -> None:
        assert self._stream_id
        record._info.stream_id = self._stream_id

    def _publish(self, record: "pb.Record", local: Optional[bool] = None) -> None:
        self._assign(record)
        self._sock_client.send_record_publish(record)
