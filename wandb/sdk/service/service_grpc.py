"""grpc service.

Implement ServiceInterface for grpc transport.
"""

import logging
from typing import Optional
from typing import TYPE_CHECKING

import grpc
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_server_pb2_grpc as pbgrpc

from .service_base import _pbmap_apply_dict
from .service_base import ServiceInterface

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


class ServiceGrpcInterface(ServiceInterface):
    _stub: Optional[pbgrpc.InternalServiceStub]

    def __init__(self) -> None:
        self._stub = None

    def get_transport(self) -> str:
        return "grpc"

    def _svc_connect(self, port: int) -> None:
        channel = grpc.insecure_channel("localhost:{}".format(port))
        stub = pbgrpc.InternalServiceStub(channel)
        self._stub = stub
        # TODO: make sure service is up

    def _get_stub(self) -> pbgrpc.InternalServiceStub:
        assert self._stub
        return self._stub

    def _svc_inform_init(self, settings: "Settings", run_id: str) -> None:
        inform_init = spb.ServerInformInitRequest()
        settings_dict = settings.make_static()
        settings_dict["_log_level"] = logging.DEBUG
        _pbmap_apply_dict(inform_init._settings_map, settings_dict)
        inform_init._info.stream_id = run_id

        assert self._stub
        _ = self._stub.ServerInformInit(inform_init)

    def _svc_inform_finish(self, run_id: str = None) -> None:
        assert run_id
        inform_fin = spb.ServerInformFinishRequest()
        inform_fin._info.stream_id = run_id

        assert self._stub
        _ = self._stub.ServerInformFinish(inform_fin)

    def _svc_inform_attach(self, attach_id: str) -> None:
        assert self._stub

        inform_attach = spb.ServerInformAttachRequest()
        inform_attach._info.stream_id = attach_id
        _ = self._stub.ServerInformAttach(inform_attach)

    def _svc_inform_teardown(self, exit_code: int) -> None:
        inform_teardown = spb.ServerInformTeardownRequest(exit_code=exit_code)

        assert self._stub
        _ = self._stub.ServerInformTeardown(inform_teardown)
