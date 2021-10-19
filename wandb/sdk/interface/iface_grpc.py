# -*- coding: utf-8 -*-
"""Backend Sender - Send to internal process

Manage backend sender.

"""

import logging
from typing import Any, Optional
from typing import TYPE_CHECKING

import grpc
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
    _stream_id: Optional[str]

    def __init__(self) -> None:
        super(BackendGrpcSender, self).__init__()
        self._stub = None
        self._process_check = None
        self._stream_id = None

    def _hack_set_run(self, run: "Run") -> None:
        super(BackendGrpcSender, self)._hack_set_run(run)
        assert run.id
        self._stream_id = run.id

    def _connect(self, stub: pbgrpc.InternalServiceStub) -> None:
        self._stub = stub

    def _assign(self, record: Any) -> None:
        assert self._stream_id
        record._info.stream_id = self._stream_id

    def _communicate_check_version(
        self, check_version: pb.CheckVersionRequest
    ) -> Optional[pb.CheckVersionResponse]:
        assert self._stub
        self._assign(check_version)
        run_result = self._stub.CheckVersion(check_version)
        return run_result

    def _communicate_attach(
        self, attach: pb.AttachRequest
    ) -> Optional[pb.AttachResponse]:
        assert self._stub
        self._assign(attach)
        resp = self._stub.Attach(attach)
        return resp

    def _communicate_run(
        self, run: pb.RunRecord, timeout: int = None
    ) -> Optional[pb.RunUpdateResult]:
        assert self._stub
        self._assign(run)
        run_result = self._stub.RunUpdate(run)
        return run_result

    def _publish_run(self, run: pb.RunRecord) -> None:
        assert self._stub
        self._assign(run)
        _ = self._stub.RunUpdate(run)

    def _publish_config(self, cfg: pb.ConfigRecord) -> None:
        assert self._stub
        self._assign(cfg)
        _ = self._stub.Config(cfg)

    def _publish_metric(self, metric: pb.MetricRecord) -> None:
        assert self._stub
        self._assign(metric)
        _ = self._stub.Metric(metric)

    def _publish_summary(self, summary: pb.SummaryRecord) -> None:
        assert self._stub
        self._assign(summary)
        _ = self._stub.Summary(summary)

    def _communicate_get_summary(
        self, get_summary: pb.GetSummaryRequest
    ) -> Optional[pb.GetSummaryResponse]:
        assert self._stub
        self._assign(get_summary)
        try:
            resp = self._stub.GetSummary(get_summary)
        except grpc.RpcError as e:
            logger.info(f"GET SUMMARY TIMEOUT: {e}")
            resp = pb.GetSummaryResponse()
        return resp

    def _publish_telemetry(self, telem: tpb.TelemetryRecord) -> None:
        assert self._stub
        self._assign(telem)
        _ = self._stub.Telemetry(telem)

    def _publish_history(self, history: pb.HistoryRecord) -> None:
        assert self._stub
        self._assign(history)
        _ = self._stub.Log(history)

    def _publish_preempting(self, preempt_rec: pb.RunPreemptingRecord) -> None:
        assert self._stub
        self._assign(preempt_rec)
        _ = self._stub.RunPreempting(preempt_rec)

    def _publish_output(self, outdata: pb.OutputRecord) -> None:
        assert self._stub
        self._assign(outdata)
        _ = self._stub.Output(outdata)

    def _communicate_shutdown(self) -> None:
        assert self._stub
        shutdown = pb.ShutdownRequest()
        self._assign(shutdown)
        _ = self._stub.Shutdown(shutdown)

    def _communicate_run_start(
        self, run_start: pb.RunStartRequest
    ) -> Optional[pb.RunStartResponse]:
        assert self._stub
        self._assign(run_start)
        try:
            run_start_response = self._stub.RunStart(run_start)
        except grpc.RpcError as e:
            logger.info(f"RUNSTART TIMEOUT: {e}")
            run_start_response = pb.RunStartResponse()
        return run_start_response

    def _publish_files(self, files: pb.FilesRecord) -> None:
        assert self._stub
        self._assign(files)
        _ = self._stub.Files(files)

    def _publish_artifact(self, proto_artifact: pb.ArtifactRecord) -> None:
        assert self._stub
        # TODO: implement

    def _communicate_artifact(
        self, log_artifact: pb.LogArtifactRequest
    ) -> MessageFuture:
        assert self._stub
        self._assign(log_artifact)
        # TODO: implement
        dummy = pb.Result()
        future = MessageFuture()
        future._set_object(dummy)
        return future

    def _communicate_status(
        self, status: pb.StatusRequest
    ) -> Optional[pb.StatusResponse]:
        assert self._stub
        self._assign(status)
        status_response = self._stub.Status(status)
        return status_response

    def _communicate_network_status(
        self, status: pb.NetworkStatusRequest
    ) -> Optional[pb.NetworkStatusResponse]:
        assert self._stub
        self._assign(status)
        # TODO: implement
        return None

    def _communicate_stop_status(
        self, status: pb.StopStatusRequest
    ) -> Optional[pb.StopStatusResponse]:
        assert self._stub
        self._assign(status)
        # TODO: implement
        return None

    def _publish_alert(self, alert: pb.AlertRecord) -> None:
        assert self._stub
        self._assign(alert)
        _ = self._stub.Alert(alert)

    def _publish_tbdata(self, tbrecord: pb.TBRecord) -> None:
        assert self._stub
        self._assign(tbrecord)
        _ = self._stub.TBSend(tbrecord)

    def _publish_exit(self, exit_data: pb.RunExitRecord) -> None:
        assert self._stub
        self._assign(exit_data)
        _ = self._stub.RunExit(exit_data)
        return None

    def _communicate_poll_exit(
        self, poll_exit: pb.PollExitRequest
    ) -> Optional[pb.PollExitResponse]:
        assert self._stub
        self._assign(poll_exit)
        try:
            ret = self._stub.PollExit(poll_exit)
        except grpc.RpcError as e:
            logger.info(f"POLL EXIT TIMEOUT: {e}")
            ret = pb.PollExitResponse()
        return ret

    def _communicate_sampled_history(
        self, sampled_history: pb.SampledHistoryRequest
    ) -> Optional[pb.SampledHistoryResponse]:
        assert self._stub
        self._assign(sampled_history)
        ret = self._stub.SampledHistory(sampled_history)
        return ret

    def _publish_header(self, header: pb.HeaderRecord) -> None:
        assert self._stub
        # TODO: implement?

    def _publish_pause(self, pause: pb.PauseRequest) -> None:
        assert self._stub
        self._assign(pause)
        _ = self._stub.Pause(pause)

    def _publish_resume(self, resume: pb.ResumeRequest) -> None:
        assert self._stub
        self._assign(resume)
        _ = self._stub.Resume(resume)

    def join(self) -> None:
        super(BackendGrpcSender, self).join()
