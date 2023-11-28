"""socket service.

Implement ServiceInterface for socket transport.
"""

from typing import TYPE_CHECKING, Optional

from wandb.proto import wandb_server_pb2 as spb

from ..lib.sock_client import SockClient
from .service_base import ServiceInterface

if TYPE_CHECKING:
    from wandb.proto import wandb_settings_pb2


class ServiceSockInterface(ServiceInterface):
    _sock_client: SockClient

    def __init__(self) -> None:
        self._sock_client = SockClient()

    def get_transport(self) -> str:
        return "tcp"

    def _get_sock_client(self) -> SockClient:
        return self._sock_client

    def _svc_connect(self, port: int) -> None:
        self._sock_client.connect(port=port)

    def _svc_inform_init(
        self, settings: "wandb_settings_pb2.Settings", run_id: str
    ) -> None:
        inform_init = spb.ServerInformInitRequest()
        inform_init.settings.CopyFrom(settings)
        inform_init._info.stream_id = run_id
        assert self._sock_client
        self._sock_client.send(inform_init=inform_init)

    def _svc_inform_start(
        self, settings: "wandb_settings_pb2.Settings", run_id: str
    ) -> None:
        inform_start = spb.ServerInformStartRequest()
        inform_start.settings.CopyFrom(settings)
        inform_start._info.stream_id = run_id
        assert self._sock_client
        self._sock_client.send(inform_start=inform_start)

    def _svc_inform_finish(self, run_id: Optional[str] = None) -> None:
        assert run_id
        inform_finish = spb.ServerInformFinishRequest()
        inform_finish._info.stream_id = run_id

        assert self._sock_client
        self._sock_client.send(inform_finish=inform_finish)

    def _svc_inform_attach(self, attach_id: str) -> spb.ServerInformAttachResponse:
        inform_attach = spb.ServerInformAttachRequest()
        inform_attach._info.stream_id = attach_id

        assert self._sock_client
        response = self._sock_client.send_and_recv(inform_attach=inform_attach)
        return response.inform_attach_response

    def _svc_inform_teardown(self, exit_code: int) -> None:
        inform_teardown = spb.ServerInformTeardownRequest(exit_code=exit_code)

        assert self._sock_client
        self._sock_client.send(inform_teardown=inform_teardown)
