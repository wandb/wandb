from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from typing_extensions import override

from wandb.proto import wandb_server_pb2 as spb

from .interface_shared import InterfaceShared

if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2 as pb
    from wandb.sdk.lib.service.service_client import ServiceClient
    from wandb.sdk.mailbox import MailboxHandle


logger = logging.getLogger("wandb")


class InterfaceSock(InterfaceShared):
    def __init__(
        self,
        client: ServiceClient,
        stream_id: str,
    ) -> None:
        super().__init__()
        self._client = client
        self._stream_id = stream_id

    def _assign(self, record: Any) -> None:
        assert self._stream_id
        record._info.stream_id = self._stream_id

    @override
    def _publish(self, record: pb.Record, local: bool | None = None) -> None:
        self._assign(record)
        request = spb.ServerRequest()
        request.record_publish.CopyFrom(record)
        self._client.publish(request)

    @override
    def _deliver(self, record: pb.Record) -> MailboxHandle[pb.Result]:
        self._assign(record)
        request = spb.ServerRequest()
        request.record_publish.CopyFrom(record)

        handle = self._client.deliver(request)
        return handle.map(lambda response: response.result_communicate)
