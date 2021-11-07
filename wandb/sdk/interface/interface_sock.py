"""InterfaceSock - Derived from InterfaceShared using a socket to send to internal thread

See interface.py for how interface classes relate to each other.

"""

import logging
from typing import Any, Optional
from typing import TYPE_CHECKING


from .interface_shared import InterfaceShared
from .message_future import MessageFuture
from .router_sock import MessageSockRouter
from ..lib.sock_client import SockClient


if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2 as pb
    from ..wandb_run import Run


logger = logging.getLogger("wandb")


class InterfaceSock(InterfaceShared):
    _stream_id: Optional[str]
    _sock_client: SockClient

    def __init__(self, sock_client: SockClient) -> None:
        self._sock_client = sock_client
        super(InterfaceSock, self).__init__()
        self._process_check = False
        self._stream_id = None

    def _init_router(self) -> None:
        self._router = MessageSockRouter(self._sock_client)

    def _hack_set_run(self, run: "Run") -> None:
        super(InterfaceSock, self)._hack_set_run(run)
        assert run.id
        self._stream_id = run.id

    def _assign(self, record: Any) -> None:
        assert self._stream_id
        record._info.stream_id = self._stream_id

    def _publish(self, record: "pb.Record", local: bool = None) -> None:
        self._assign(record)
        self._sock_client.send_record_publish(record)

    def _communicate_async(self, rec: "pb.Record", local: bool = None) -> MessageFuture:
        self._assign(rec)
        rec.control.relay = True
        assert self._router
        if self._process_check and self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
        future = self._router.send_and_receive(rec, local=local)
        return future
