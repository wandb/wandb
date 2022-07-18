"""grpc server.

Implement grpc servicer.
"""

from typing import TYPE_CHECKING

import grpc
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_server_pb2_grpc as spb_grpc
from wandb.proto import wandb_telemetry_pb2 as tpb

from .service_base import _pbmap_apply_dict
from .streams import StreamMux
from .. import lib as wandb_lib
from ..lib.proto_util import settings_dict_from_pbmap


if TYPE_CHECKING:

    class GrpcServerType:
        def __init__(self) -> None:
            pass

        def stop(self, num: int) -> None:
            pass


class WandbServicer(spb_grpc.InternalServiceServicer):
    """Provides methods that implement functionality of route guide server."""

    _server: "GrpcServerType"
    _mux: StreamMux

    def __init__(self, server: "GrpcServerType", mux: StreamMux) -> None:
        self._server = server
        self._mux = mux

    def RunUpdate(  # noqa: N802
        self, run_data: pb.RunRecord, context: grpc.ServicerContext
    ) -> pb.RunUpdateResult:
        if not run_data.run_id:
            run_data.run_id = wandb_lib.runid.generate_id()
        # Record telemetry info about grpc server
        run_data.telemetry.feature.grpc = True
        run_data.telemetry.cli_version = wandb.__version__
        stream_id = run_data._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        result = iface._communicate_run(run_data)
        assert result  # TODO: handle errors
        return result

    def RunStart(  # noqa: N802
        self, run_start: pb.RunStartRequest, context: grpc.ServicerContext
    ) -> pb.RunStartResponse:
        # initiate run (stats and metadata probing)
        stream_id = run_start._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        result = iface._communicate_run_start(run_start)
        assert result  # TODO: handle errors
        return result

    def CheckVersion(  # noqa: N802
        self, check_version: pb.CheckVersionRequest, context: grpc.ServicerContext
    ) -> pb.CheckVersionResponse:
        # result = self._servicer._interface._communicate_check_version(check_version)
        # assert result  # TODO: handle errors
        result = pb.CheckVersionResponse()
        return result

    def Attach(  # noqa: N802
        self, attach: pb.AttachRequest, context: grpc.ServicerContext
    ) -> pb.AttachResponse:
        stream_id = attach._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        result = iface._communicate_attach(attach)
        assert result  # TODO: handle errors
        return result

    def PollExit(  # noqa: N802
        self, poll_exit: pb.PollExitRequest, context: grpc.ServicerContext
    ) -> pb.PollExitResponse:
        stream_id = poll_exit._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        result = iface.communicate_poll_exit()
        assert result  # TODO: handle errors
        return result

    def GetSummary(  # noqa: N802
        self, get_summary: pb.GetSummaryRequest, context: grpc.ServicerContext
    ) -> pb.GetSummaryResponse:
        stream_id = get_summary._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        result = iface.communicate_get_summary()
        assert result  # TODO: handle errors
        return result

    def SampledHistory(  # noqa: N802
        self, sampled_history: pb.SampledHistoryRequest, context: grpc.ServicerContext
    ) -> pb.SampledHistoryResponse:
        stream_id = sampled_history._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        result = iface.communicate_sampled_history()
        assert result  # TODO: handle errors
        return result

    def Shutdown(  # noqa: N802
        self, shutdown: pb.ShutdownRequest, context: grpc.ServicerContext
    ) -> pb.ShutdownResponse:
        stream_id = shutdown._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._communicate_shutdown()
        result = pb.ShutdownResponse()
        return result

    def RunExit(  # noqa: N802
        self, exit_data: pb.RunExitRecord, context: grpc.ServicerContext
    ) -> pb.RunExitResult:
        stream_id = exit_data._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface.publish_exit(exit_data.exit_code)
        result = pb.RunExitResult()
        return result

    def RunPreempting(  # noqa: N802
        self, preempt: pb.RunPreemptingRecord, context: grpc.ServicerContext
    ) -> pb.RunPreemptingResult:
        stream_id = preempt._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_preempting(preempt)
        result = pb.RunPreemptingResult()
        return result

    def Artifact(  # noqa: N802
        self, art_data: pb.ArtifactRecord, context: grpc.ServicerContext
    ) -> pb.ArtifactResult:
        stream_id = art_data._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_artifact(art_data)
        result = pb.ArtifactResult()
        return result

    def LinkArtifact(  # noqa: N802
        self,
        link_artifact: pb.LinkArtifactRecord,
        context: grpc.ServicerContext,
    ) -> pb.LinkArtifactResult:
        stream_id = link_artifact._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_link_artifact(link_artifact)
        result = pb.LinkArtifactResult()
        return result

    def ArtifactSend(  # noqa: N802
        self, art_send: pb.ArtifactSendRequest, context: grpc.ServicerContext
    ) -> pb.ArtifactSendResponse:
        stream_id = art_send._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        resp = iface._communicate_artifact_send(art_send)
        assert resp
        return resp

    def ArtifactPoll(  # noqa: N802
        self, art_poll: pb.ArtifactPollRequest, context: grpc.ServicerContext
    ) -> pb.ArtifactPollResponse:
        stream_id = art_poll._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        resp = iface._communicate_artifact_poll(art_poll)
        assert resp
        return resp

    def TBSend(  # noqa: N802
        self, tb_data: pb.TBRecord, context: grpc.ServicerContext
    ) -> pb.TBResult:
        stream_id = tb_data._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_tbdata(tb_data)
        result = pb.TBResult()
        return result

    def PartialLog(  # noqa: N802
        self, partial_history: pb.PartialHistoryRequest, context: grpc.ServicerContext
    ) -> pb.PartialHistoryResponse:
        stream_id = partial_history._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_partial_history(partial_history)
        # make up a response even though this was async
        result = pb.PartialHistoryResponse()
        return result

    def Log(  # noqa: N802
        self, history: pb.HistoryRecord, context: grpc.ServicerContext
    ) -> pb.HistoryResult:
        stream_id = history._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_history(history)
        # make up a response even though this was async
        result = pb.HistoryResult()
        return result

    def Summary(  # noqa: N802
        self, summary: pb.SummaryRecord, context: grpc.ServicerContext
    ) -> pb.SummaryResult:
        stream_id = summary._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_summary(summary)
        # make up a response even though this was async
        result = pb.SummaryResult()
        return result

    def Telemetry(  # noqa: N802
        self, telem: tpb.TelemetryRecord, context: grpc.ServicerContext
    ) -> tpb.TelemetryResult:
        stream_id = telem._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_telemetry(telem)
        # make up a response even though this was async
        result = tpb.TelemetryResult()
        return result

    def Output(  # noqa: N802
        self, output_data: pb.OutputRecord, context: grpc.ServicerContext
    ) -> pb.OutputResult:
        stream_id = output_data._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_output(output_data)
        # make up a response even though this was async
        result = pb.OutputResult()
        return result

    def OutputRaw(  # noqa: N802
        self, output_data: pb.OutputRawRecord, context: grpc.ServicerContext
    ) -> pb.OutputRawResult:
        stream_id = output_data._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_output_raw(output_data)
        # make up a response even though this was async
        result = pb.OutputRawResult()
        return result

    def Files(  # noqa: N802
        self, files_data: pb.FilesRecord, context: grpc.ServicerContext
    ) -> pb.FilesResult:
        stream_id = files_data._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_files(files_data)
        # make up a response even though this was async
        result = pb.FilesResult()
        return result

    def Config(  # noqa: N802
        self, config_data: pb.ConfigRecord, context: grpc.ServicerContext
    ) -> pb.ConfigResult:
        stream_id = config_data._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_config(config_data)
        # make up a response even though this was async
        result = pb.ConfigResult()
        return result

    def Metric(  # noqa: N802
        self, metric: pb.MetricRecord, context: grpc.ServicerContext
    ) -> pb.MetricResult:
        stream_id = metric._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_metric(metric)
        # make up a response even though this was async
        result = pb.MetricResult()
        return result

    def Pause(  # noqa: N802
        self, pause: pb.PauseRequest, context: grpc.ServicerContext
    ) -> pb.PauseResponse:
        stream_id = pause._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_pause(pause)
        # make up a response even though this was async
        result = pb.PauseResponse()
        return result

    def Resume(  # noqa: N802
        self, resume: pb.ResumeRequest, context: grpc.ServicerContext
    ) -> pb.ResumeResponse:
        stream_id = resume._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_resume(resume)
        # make up a response even though this was async
        result = pb.ResumeResponse()
        return result

    def Alert(  # noqa: N802
        self, alert: pb.AlertRecord, context: grpc.ServicerContext
    ) -> pb.AlertResult:
        stream_id = alert._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        iface._publish_alert(alert)
        # make up a response even though this was async
        result = pb.AlertResult()
        return result

    def Status(  # noqa: N802
        self, status: pb.StatusRequest, context: grpc.ServicerContext
    ) -> pb.StatusResponse:
        stream_id = status._info.stream_id
        iface = self._mux.get_stream(stream_id).interface
        result = iface._communicate_status(status)
        assert result
        return result

    def ServerShutdown(  # noqa: N802
        self,
        request: spb.ServerShutdownRequest,
        context: grpc.ServicerContext,
    ) -> spb.ServerShutdownResponse:
        result = spb.ServerShutdownResponse()
        self._server.stop(5)
        return result

    def ServerStatus(  # noqa: N802
        self,
        request: spb.ServerStatusRequest,
        context: grpc.ServicerContext,
    ) -> spb.ServerStatusResponse:
        result = spb.ServerStatusResponse()
        return result

    def ServerInformInit(  # noqa: N802
        self,
        request: spb.ServerInformInitRequest,
        context: grpc.ServicerContext,
    ) -> spb.ServerInformInitResponse:
        stream_id = request._info.stream_id
        settings = settings_dict_from_pbmap(request._settings_map)
        self._mux.add_stream(stream_id, settings=settings)
        result = spb.ServerInformInitResponse()
        return result

    def ServerInformStart(  # noqa: N802
        self,
        request: spb.ServerInformStartRequest,
        context: grpc.ServicerContext,
    ) -> spb.ServerInformStartResponse:
        stream_id = request._info.stream_id
        settings = settings_dict_from_pbmap(request._settings_map)
        self._mux.update_stream(stream_id, settings=settings)
        result = spb.ServerInformStartResponse()
        return result

    def ServerInformFinish(  # noqa: N802
        self,
        request: spb.ServerInformFinishRequest,
        context: grpc.ServicerContext,
    ) -> spb.ServerInformFinishResponse:
        stream_id = request._info.stream_id
        self._mux.del_stream(stream_id)
        result = spb.ServerInformFinishResponse()
        return result

    def ServerInformAttach(  # noqa: N802
        self,
        request: spb.ServerInformAttachRequest,
        context: grpc.ServicerContext,
    ) -> spb.ServerInformAttachResponse:
        stream_id = request._info.stream_id
        result = spb.ServerInformAttachResponse()
        _pbmap_apply_dict(
            result._settings_map,
            dict(self._mux._streams[stream_id]._settings),
        )
        return result

    def ServerInformDetach(  # noqa: N802
        self,
        request: spb.ServerInformDetachRequest,
        context: grpc.ServicerContext,
    ) -> spb.ServerInformDetachResponse:
        # TODO
        result = spb.ServerInformDetachResponse()
        return result

    def ServerInformTeardown(  # noqa: N802
        self,
        request: spb.ServerInformTeardownRequest,
        context: grpc.ServicerContext,
    ) -> spb.ServerInformTeardownResponse:
        exit_code = request.exit_code
        self._mux.teardown(exit_code)
        result = spb.ServerInformTeardownResponse()
        return result
