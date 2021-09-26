#
# -*- coding: utf-8 -*-
"""Backend Sender - Send to internal process

Manage backend sender.

"""

import logging
from typing import Optional
from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2_grpc as pbgrpc
from wandb.proto import wandb_telemetry_pb2 as tpb

from .interface import BackendSenderBase
from .router import MessageFuture


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

    def _hack_set_run(self, run: "Run") -> None:
        super(BackendGrpcSender, self)._hack_set_run(run)
        if self._grpc_port:
            run._set_iface_port(self._grpc_port)

    def _connect(self, stub: pbgrpc.InternalServiceStub) -> None:
        self._stub = stub

    def _communicate_check_version(
        self, check_version: pb.CheckVersionRequest
    ) -> Optional[pb.CheckVersionResponse]:
        assert self._stub
        run_result = self._stub.CheckVersion(check_version)
        return run_result

    def _communicate_attach(
        self, attach: pb.AttachRequest
    ) -> Optional[pb.AttachResponse]:
        assert self._stub
        resp = self._stub.Attach(attach)
        return resp

    def _communicate_run(
        self, run: pb.RunRecord, timeout: int = None
    ) -> Optional[pb.RunUpdateResult]:
        assert self._stub
        run_result = self._stub.RunUpdate(run)
        return run_result

    def _publish_run(self, run: pb.RunRecord) -> None:
        assert self._stub
        _ = self._stub.RunUpdate(run)

    def _publish_config(self, cfg: pb.ConfigRecord) -> None:
        assert self._stub
        _ = self._stub.Config(cfg)

    def _publish_metric(self, metric: pb.MetricRecord) -> None:
        assert self._stub
        _ = self._stub.Metric(metric)

    def _publish_summary(self, summary: pb.SummaryRecord) -> None:
        assert self._stub
        _ = self._stub.Summary(summary)

    def _communicate_get_summary(
        self, get_summary: pb.GetSummaryRequest
    ) -> Optional[pb.GetSummaryResponse]:
        assert self._stub
        resp = self._stub.GetSummary(get_summary)
        return resp

    def _publish_telemetry(self, telem: tpb.TelemetryRecord) -> None:
        assert self._stub
        _ = self._stub.Telemetry(telem)

    def _publish_history(self, history: pb.HistoryRecord) -> None:
        assert self._stub
        _ = self._stub.Log(history)

    def _publish_preempting(self, preempt_rec: pb.RunPreemptingRecord) -> None:
        assert self._stub
        _ = self._stub.RunPreempting(preempt_rec)

    def _publish_output(self, outdata: pb.OutputRecord) -> None:
        assert self._stub
        _ = self._stub.Output(outdata)

    def _communicate_shutdown(self) -> None:
        assert self._stub
        shutdown = pb.ShutdownRequest()
        _ = self._stub.Shutdown(shutdown)

    def _communicate_run_start(
        self, run_start: pb.RunStartRequest
    ) -> Optional[pb.RunStartResponse]:
        assert self._stub
        run_start_response = self._stub.RunStart(run_start)
        return run_start_response

    def _publish_files(self, files: pb.FilesRecord) -> None:
        assert self._stub
        _ = self._stub.Files(files)

    def _publish_artifact(self, proto_artifact: pb.ArtifactRecord) -> None:
        # TODO: implement
        pass

    def _communicate_artifact(
        self, log_artifact: pb.LogArtifactRequest
    ) -> MessageFuture:
        # TODO: implement
        dummy = pb.Result()
        future = MessageFuture()
        future._set_object(dummy)
        return future

    def _communicate_network_status(
        self, status: pb.NetworkStatusRequest
    ) -> Optional[pb.NetworkStatusResponse]:
        # TODO: implement
        pass

    def _communicate_stop_status(
        self, status: pb.StopStatusRequest
    ) -> Optional[pb.StopStatusResponse]:
        # TODO: implement
        pass

    def _publish_alert(self, alert: pb.AlertRecord) -> None:
        # TODO: implement
        pass

    def _publish_tbdata(self, tbrecord: pb.TBRecord) -> None:
        # TODO: implement
        pass

    def _publish_exit(self, exit_data: pb.RunExitRecord) -> None:
        assert self._stub
        _ = self._stub.RunExit(exit_data)
        return None

    def _communicate_poll_exit(
        self, poll_exit: pb.PollExitRequest
    ) -> Optional[pb.PollExitResponse]:
        assert self._stub
        ret = self._stub.PollExit(poll_exit)
        return ret

    def _communicate_sampled_history(
        self, sampled_history: pb.SampledHistoryRequest
    ) -> Optional[pb.SampledHistoryResponse]:
        assert self._stub
        ret = self._stub.SampledHistory(sampled_history)
        return ret

    def _publish_header(self, header: pb.HeaderRecord) -> None:
        # TODO: implement?
        pass

    def _publish_pause(self, pause: pb.PauseRequest) -> None:
        assert self._stub
        _ = self._stub.Pause(pause)

    def _publish_resume(self, resume: pb.ResumeRequest) -> None:
        assert self._stub
        _ = self._stub.Resume(resume)

    def join(self) -> None:
        super(BackendGrpcSender, self).join()
