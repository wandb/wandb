#!/usr/bin/env python
"""wandb grpc server.

- WandbServer:
- StreamMux:
- StreamRecord:
- WandbServicer:

"""

from concurrent import futures
import logging
import sys
from typing import Optional
from typing import TYPE_CHECKING

import grpc
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_server_pb2_grpc as spb_grpc
from wandb.proto import wandb_telemetry_pb2 as tpb

from . import port_file
from .server_sock import SocketServer
from .streams import _dict_from_pbmap
from .streams import StreamMux
from .. import lib as wandb_lib


if TYPE_CHECKING:

    class GrpcServerType(object):
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
        self, request: spb.ServerShutdownRequest, context: grpc.ServicerContext,
    ) -> spb.ServerShutdownResponse:
        result = spb.ServerShutdownResponse()
        self._server.stop(5)
        return result

    def ServerStatus(  # noqa: N802
        self, request: spb.ServerStatusRequest, context: grpc.ServicerContext,
    ) -> spb.ServerStatusResponse:
        result = spb.ServerStatusResponse()
        return result

    def ServerInformInit(  # noqa: N802
        self, request: spb.ServerInformInitRequest, context: grpc.ServicerContext,
    ) -> spb.ServerInformInitResponse:
        stream_id = request._info.stream_id
        settings = _dict_from_pbmap(request._settings_map)
        self._mux.add_stream(stream_id, settings=settings)
        result = spb.ServerInformInitResponse()
        return result

    def ServerInformFinish(  # noqa: N802
        self, request: spb.ServerInformFinishRequest, context: grpc.ServicerContext,
    ) -> spb.ServerInformFinishResponse:
        stream_id = request._info.stream_id
        self._mux.del_stream(stream_id)
        result = spb.ServerInformFinishResponse()
        return result

    def ServerInformAttach(  # noqa: N802
        self, request: spb.ServerInformAttachRequest, context: grpc.ServicerContext,
    ) -> spb.ServerInformAttachResponse:
        # TODO
        result = spb.ServerInformAttachResponse()
        return result

    def ServerInformDetach(  # noqa: N802
        self, request: spb.ServerInformDetachRequest, context: grpc.ServicerContext,
    ) -> spb.ServerInformDetachResponse:
        # TODO
        result = spb.ServerInformDetachResponse()
        return result

    def ServerInformTeardown(  # noqa: N802
        self, request: spb.ServerInformTeardownRequest, context: grpc.ServicerContext,
    ) -> spb.ServerInformTeardownResponse:
        exit_code = request.exit_code
        self._mux.teardown(exit_code)
        result = spb.ServerInformTeardownResponse()
        return result


class WandbServer:
    _pid: Optional[int]
    _grpc_port: Optional[int]
    _sock_port: Optional[int]
    _debug: bool
    _serve_grpc: bool
    _serve_sock: bool
    _sock_server: Optional[SocketServer]

    def __init__(
        self,
        grpc_port: int = None,
        sock_port: int = None,
        port_fname: str = None,
        address: str = None,
        pid: int = None,
        debug: bool = False,
        serve_grpc: bool = False,
        serve_sock: bool = False,
    ) -> None:
        self._grpc_port = grpc_port
        self._sock_port = sock_port
        self._port_fname = port_fname
        self._address = address
        self._pid = pid
        self._debug = debug
        self._serve_grpc = serve_grpc
        self._serve_sock = serve_sock
        self._sock_server = None

        if grpc_port:
            _ = wandb.util.get_module(  # type: ignore
                "grpc",
                required="grpc port requires the grpcio library, run pip install wandb[grpc]",
            )

        debug = True
        if debug:
            logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    def _inform_used_ports(
        self, grpc_port: Optional[int], sock_port: Optional[int]
    ) -> None:
        if not self._port_fname:
            return
        pf = port_file.PortFile(grpc_port=grpc_port, sock_port=sock_port)
        pf.write(self._port_fname)

    def _start_grpc(self, mux: StreamMux) -> int:
        address: str = self._address or "127.0.0.1"
        port: int = self._grpc_port or 0
        pid: int = self._pid or 0
        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="GrpcPoolThr")
        )
        servicer = WandbServicer(server=server, mux=mux)
        try:
            spb_grpc.add_InternalServiceServicer_to_server(servicer, server)
            port = server.add_insecure_port(f"{address}:{port}")
            mux.set_port(port)
            mux.set_pid(pid)
            server.start()
        except KeyboardInterrupt:
            mux.cleanup()
            server.stop(0)
            raise
        except Exception:
            mux.cleanup()
            server.stop(0)
            raise
        return port

    def _start_sock(self, mux: StreamMux) -> int:
        address: str = self._address or "127.0.0.1"
        port: int = self._sock_port or 0
        # pid: int = self._pid or 0
        self._sock_server = SocketServer(mux=mux, address=address, port=port)
        try:
            self._sock_server.start()
            port = self._sock_server.port
        except KeyboardInterrupt:
            mux.cleanup()
            raise
        except Exception:
            mux.cleanup()
            raise
        return port

    def _stop_servers(self) -> None:
        if self._sock_server:
            self._sock_server.stop()

    def serve(self) -> None:
        mux = StreamMux()
        grpc_port = self._start_grpc(mux=mux) if self._serve_grpc else None
        sock_port = self._start_sock(mux=mux) if self._serve_sock else None
        self._inform_used_ports(grpc_port=grpc_port, sock_port=sock_port)
        setproctitle = wandb.util.get_optional_module("setproctitle")
        if setproctitle:
            service_ver = 0
            port = grpc_port or sock_port or 0
            service_id = f"{service_ver}-{port}"
            proc_title = f"wandb-service({service_id})"
            setproctitle.setproctitle(proc_title)
        mux.loop()
        self._stop_servers()
