#
# -*- coding: utf-8 -*-
"""Backend Sender - Send to internal process

Manage backend sender.

"""

import logging

import grpc  # type: ignore
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2
from wandb.proto import wandb_server_pb2_grpc as pbgrpc
from wandb.proto import wandb_telemetry_pb2 as tpb

from .interface import BackendSenderBase

if wandb.TYPE_CHECKING:
    from typing import Optional
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from ..wandb_run import Run


logger = logging.getLogger("wandb")


class BackendGrpcSender(BackendSenderBase):

    _stub: Optional[pbgrpc.InternalServiceStub]
    _grpc_port: Optional[int]

    def __init__(self) -> None:
        super(BackendGrpcSender, self).__init__()
        self._stub = None
        self._process_check = None
        self._grpc_port = None

    def _reconnect(self, pid: int, port: int) -> None:
        self._connect(port)
        if self._run:
            self._run._set_iface_pid(pid)
            self._run._set_iface_port(port)

    def _init_router(self) -> None:
        # no router needed, grpc has its own router
        pass

    def _hack_set_run(self, run: "Run") -> None:
        super(BackendGrpcSender, self)._hack_set_run(run)
        if self._grpc_port:
            run._set_iface_port(self._grpc_port)

    def _connect(self, port) -> None:
        channel = grpc.insecure_channel("localhost:{}".format(port))
        stub = pbgrpc.InternalServiceStub(channel)
        self._stub = stub
        d = wandb_server_pb2.ServerStatusRequest()
        _ = self._stub.ServerStatus(d)
        self._grpc_port = port

    def communicate_check_version(
        self, current_version: str = None
    ) -> Optional[pb.CheckVersionResponse]:
        pass

    def _communicate_run(
        self, run: pb.RunRecord, timeout: int = None
    ) -> Optional[pb.RunUpdateResult]:
        assert self._stub
        run_result = self._stub.RunUpdate(run)
        return run_result

    def _publish_summary(self, summary: pb.SummaryRecord) -> None:
        pass

    def _publish_telemetry(self, telem: tpb.TelemetryRecord) -> None:
        pass

    def _publish_history(self, history: pb.HistoryRecord) -> None:
        pass

    def _communicate_shutdown(self) -> None:
        assert self._stub
        shutdown = pb.ShutdownRequest()
        _ = self._stub.Shutdown(shutdown)
        return None

    def _communicate_run_start(
        self, run_start: pb.RunStartRequest
    ) -> Optional[pb.Result]:
        assert self._stub
        _ = self._stub.RunStart(run_start)
        result = pb.Result()
        return result

    def communicate_network_status(
        self, timeout: int = None
    ) -> Optional[pb.NetworkStatusResponse]:
        return None

    def communicate_stop_status(
        self, timeout: int = None
    ) -> Optional[pb.StopStatusResponse]:
        return None

    def publish_exit(self, exit_code: int) -> None:
        assert self._stub
        exit_data = self._make_exit(exit_code)
        _ = self._stub.RunExit(exit_data)
        return None

    def communicate_poll_exit(self) -> Optional[pb.PollExitResponse]:
        assert self._stub
        req = pb.PollExitRequest()
        ret = self._stub.PollExit(req)
        return ret

    def communicate_summary(self) -> Optional[pb.GetSummaryResponse]:
        assert self._stub
        req = pb.GetSummaryRequest()
        ret = self._stub.GetSummary(req)
        return ret

    def communicate_sampled_history(self) -> Optional[pb.SampledHistoryResponse]:
        assert self._stub
        req = pb.SampledHistoryRequest()
        ret = self._stub.SampledHistory(req)
        return ret

    def _publish_header(self, header: pb.HeaderRecord) -> None:
        pass

    def join(self) -> None:
        super(BackendGrpcSender, self).join()
