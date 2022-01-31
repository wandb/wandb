"""socket service.

Implement ServiceInterface for socket transport.
"""

import logging
from typing import TYPE_CHECKING

from wandb.proto import wandb_server_pb2 as spb

from .service_base import _pbmap_apply_dict
from .service_base import ServiceInterface
from ..lib.sock_client import SockClient

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


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

    def _svc_inform_init(self, settings: "Settings", run_id: str) -> None:
        inform_init = spb.ServerInformInitRequest()
        settings_dict = settings.make_static()
        settings_dict["_log_level"] = logging.DEBUG
        _pbmap_apply_dict(inform_init._settings_map, settings_dict)

        inform_init._info.stream_id = run_id
        assert self._sock_client
        self._sock_client.send(inform_init=inform_init)

    def _svc_inform_finish(self, run_id: str = None) -> None:
        assert run_id
        inform_fin = spb.ServerInformFinishRequest()
        inform_fin._info.stream_id = run_id

        assert self._sock_client
        self._sock_client.send(inform_finish=inform_fin)

    def _svc_inform_attach(self, attach_id: str) -> None:
        inform_attach = spb.ServerInformAttachRequest()
        inform_attach._info.stream_id = attach_id

        assert self._sock_client
        self._sock_client.send(inform_attach=inform_attach)

    def _svc_inform_teardown(self, exit_code: int) -> None:
        inform_teardown = spb.ServerInformTeardownRequest(exit_code=exit_code)

        assert self._sock_client
        self._sock_client.send(inform_teardown=inform_teardown)
