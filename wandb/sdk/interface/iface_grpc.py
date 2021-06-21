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
from wandb.proto import wandb_server_pb2_grpc

from .interface import BackendSender

if wandb.TYPE_CHECKING:
    from typing import Optional
    from multiprocessing import Process
    from typing import cast
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from six.moves.queue import Queue
else:

    def cast(_, val):
        return val


logger = logging.getLogger("wandb")


class BackendGrpcSender(BackendSender):
    def __init__(
        self,
        record_q: "Queue[pb.Record]" = None,
        result_q: "Queue[pb.Result]" = None,
        process: Process = None,
        process_check: bool = True,
    ) -> None:
        super(BackendGrpcSender, self).__init__(
            record_q=record_q,
            result_q=result_q,
            process=process,
            process_check=process_check,
        )
        self._stub = None
        self._process_check = None

    def _publish(self, record: pb.Record, local: bool = None) -> None:
        super(BackendGrpcSender, self)._publish(record=record, local=local)

    def _init_router(self) -> None:
        pass

    def _connect(self, port) -> None:
        channel = grpc.insecure_channel("localhost:{}".format(port))
        stub = wandb_server_pb2_grpc.InternalServiceStub(channel)
        self._stub = stub
        d = wandb_server_pb2.ServerStatusRequest()
        _ = self._stub.ServerStatus(d)

    def communicate_check_version(
        self, current_version: str = None
    ) -> Optional[pb.CheckVersionResponse]:
        pass

    def _communicate_run(
        self, run: pb.RunRecord, timeout: int = None
    ) -> Optional[pb.RunUpdateResult]:
        run_result = self._stub.RunUpdate(run)
        return run_result

    def _communicate_shutdown(self) -> None:
        shutdown = pb.ShutdownRequest()
        _ = self._stub.Shutdown(shutdown)
        return None

    def communicate_run_start(self, run_pb: pb.RunRecord) -> Optional[pb.Result]:
        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(run_pb)
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
        exit_data = self._make_exit(exit_code)
        _ = self._stub.RunExit(exit_data)
        return None

    def communicate_poll_exit(self) -> Optional[pb.PollExitResponse]:
        req = pb.PollExitRequest()
        ret = self._stub.PollExit(req)
        return ret

    def communicate_summary(self) -> Optional[pb.GetSummaryResponse]:
        req = pb.GetSummaryRequest()
        ret = self._stub.GetSummary(req)
        return ret

    def communicate_sampled_history(self) -> Optional[pb.SampledHistoryResponse]:
        req = pb.SampledHistoryRequest()
        ret = self._stub.SampledHistory(req)
        return ret
