#!/usr/bin/env python
"""wandb grpc server."""

from concurrent import futures
import datetime
import logging
import multiprocessing
import os
import sys
import tempfile
import time
from typing import Any, Dict, Optional
from typing import TYPE_CHECKING

import grpc
from six.moves import queue
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2
from wandb.proto import wandb_server_pb2_grpc
from wandb.proto import wandb_telemetry_pb2 as tpb

from .. import lib as wandb_lib
from ..interface import interface


if TYPE_CHECKING:

    class GrpcServerType(object):
        def __init__(self) -> None:
            pass

        def stop(self, num: int) -> None:
            pass


class InternalServiceServicer(wandb_server_pb2_grpc.InternalServiceServicer):
    """Provides methods that implement functionality of route guide server."""

    _server: "GrpcServerType"
    _backend: "GrpcBackend"

    def __init__(self, server: "GrpcServerType", backend: "GrpcBackend") -> None:
        self._server = server
        self._backend = backend

    def RunUpdate(  # noqa: N802
        self, run_data: pb.RunRecord, context: grpc.ServicerContext
    ) -> pb.RunUpdateResult:
        if not run_data.run_id:
            run_data.run_id = wandb_lib.runid.generate_id()
        # Record telemetry info about grpc server
        run_data.telemetry.feature.grpc = True
        run_data.telemetry.cli_version = wandb.__version__
        assert self._backend and self._backend._interface
        result = self._backend._interface._communicate_run(run_data)
        assert result  # TODO: handle errors
        return result

    def RunStart(  # noqa: N802
        self, run_start: pb.RunStartRequest, context: grpc.ServicerContext
    ) -> pb.RunStartResponse:
        # initiate run (stats and metadata probing)
        assert self._backend and self._backend._interface
        result = self._backend._interface._communicate_run_start(run_start)
        assert result  # TODO: handle errors
        return result

    def CheckVersion(  # noqa: N802
        self, check_version: pb.CheckVersionRequest, context: grpc.ServicerContext
    ) -> pb.CheckVersionResponse:
        assert self._backend and self._backend._interface
        result = self._backend._interface._communicate_check_version(check_version)
        assert result  # TODO: handle errors
        return result

    def Attach(  # noqa: N802
        self, attach: pb.AttachRequest, context: grpc.ServicerContext
    ) -> pb.AttachResponse:
        assert self._backend and self._backend._interface
        result = self._backend._interface._communicate_attach(attach)
        assert result  # TODO: handle errors
        return result

    def PollExit(  # noqa: N802
        self, poll_exit: pb.PollExitRequest, context: grpc.ServicerContext
    ) -> pb.PollExitResponse:
        assert self._backend and self._backend._interface
        result = self._backend._interface.communicate_poll_exit()
        assert result  # TODO: handle errors
        return result

    def GetSummary(  # noqa: N802
        self, get_summary: pb.GetSummaryRequest, context: grpc.ServicerContext
    ) -> pb.GetSummaryResponse:
        assert self._backend and self._backend._interface
        result = self._backend._interface.communicate_get_summary()
        assert result  # TODO: handle errors
        return result

    def SampledHistory(  # noqa: N802
        self, sampled_history: pb.SampledHistoryRequest, context: grpc.ServicerContext
    ) -> pb.SampledHistoryResponse:
        assert self._backend and self._backend._interface
        result = self._backend._interface.communicate_sampled_history()
        assert result  # TODO: handle errors
        return result

    def Shutdown(  # noqa: N802
        self, shutdown: pb.ShutdownRequest, context: grpc.ServicerContext
    ) -> pb.ShutdownResponse:
        assert self._backend and self._backend._interface
        self._backend._interface._communicate_shutdown()
        result = pb.ShutdownResponse()
        return result

    def RunExit(  # noqa: N802
        self, exit_data: pb.RunExitRecord, context: grpc.ServicerContext
    ) -> pb.RunExitResult:
        assert self._backend and self._backend._interface
        self._backend._interface.publish_exit(exit_data.exit_code)
        result = pb.RunExitResult()
        return result

    def RunPreempting(  # noqa: N802
        self, preempt: pb.RunPreemptingRecord, context: grpc.ServicerContext
    ) -> pb.RunPreemptingResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_preempting(preempt)
        result = pb.RunPreemptingResult()
        return result

    def TBSend(  # noqa: N802
        self, tb_data: pb.TBRecord, context: grpc.ServicerContext
    ) -> pb.TBResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_tbdata(tb_data)
        result = pb.TBResult()
        return result

    def Log(  # noqa: N802
        self, history: pb.HistoryRecord, context: grpc.ServicerContext
    ) -> pb.HistoryResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_history(history)
        # make up a response even though this was async
        result = pb.HistoryResult()
        return result

    def Summary(  # noqa: N802
        self, summary: pb.SummaryRecord, context: grpc.ServicerContext
    ) -> pb.SummaryResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_summary(summary)
        # make up a response even though this was async
        result = pb.SummaryResult()
        return result

    def Telemetry(  # noqa: N802
        self, telem: tpb.TelemetryRecord, context: grpc.ServicerContext
    ) -> tpb.TelemetryResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_telemetry(telem)
        # make up a response even though this was async
        result = tpb.TelemetryResult()
        return result

    def Output(  # noqa: N802
        self, output_data: pb.OutputRecord, context: grpc.ServicerContext
    ) -> pb.OutputResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_output(output_data)
        # make up a response even though this was async
        result = pb.OutputResult()
        return result

    def Files(  # noqa: N802
        self, files_data: pb.FilesRecord, context: grpc.ServicerContext
    ) -> pb.FilesResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_files(files_data)
        # make up a response even though this was async
        result = pb.FilesResult()
        return result

    def Config(  # noqa: N802
        self, config_data: pb.ConfigRecord, context: grpc.ServicerContext
    ) -> pb.ConfigResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_config(config_data)
        # make up a response even though this was async
        result = pb.ConfigResult()
        return result

    def Metric(  # noqa: N802
        self, metric: pb.MetricRecord, context: grpc.ServicerContext
    ) -> pb.MetricResult:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_metric(metric)
        # make up a response even though this was async
        result = pb.MetricResult()
        return result

    def Pause(  # noqa: N802
        self, pause: pb.PauseRequest, context: grpc.ServicerContext
    ) -> pb.PauseResponse:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_pause(pause)
        # make up a response even though this was async
        result = pb.PauseResponse()
        return result

    def Resume(  # noqa: N802
        self, resume: pb.ResumeRequest, context: grpc.ServicerContext
    ) -> pb.ResumeResponse:
        assert self._backend and self._backend._interface
        self._backend._interface._publish_resume(resume)
        # make up a response even though this was async
        result = pb.ResumeResponse()
        return result

    def ServerShutdown(  # noqa: N802
        self,
        request: wandb_server_pb2.ServerShutdownRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerShutdownResponse:
        assert self._backend and self._backend._interface
        self._backend.cleanup()
        result = wandb_server_pb2.ServerShutdownResponse()
        self._server.stop(5)
        return result

    def ServerStatus(  # noqa: N802
        self,
        request: wandb_server_pb2.ServerStatusRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerStatusResponse:
        assert self._backend and self._backend._interface
        result = wandb_server_pb2.ServerStatusResponse()
        return result

    def ServerInformInit(  # noqa: N802
        self,
        request: wandb_server_pb2.ServerInformInitRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerInformInitResponse:
        assert self._backend and self._backend._interface
        result = wandb_server_pb2.ServerInformInitResponse()
        return result

    def ServerInformFinish(  # noqa: N802
        self,
        request: wandb_server_pb2.ServerInformFinishRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerInformFinishResponse:
        assert self._backend and self._backend._interface
        result = wandb_server_pb2.ServerInformFinishResponse()
        return result


# TODO(jhr): this should be merged with code in backend/backend.py ensure launched
class GrpcBackend:
    _interface: interface.BackendSender
    _settings: Dict[str, Any]
    _process: multiprocessing.process.BaseProcess
    _record_q: "queue.Queue[pb.Record]"
    _result_q: "queue.Queue[pb.Result]"
    _monitor_pid: Optional[int]

    def __init__(self, pid: int = None, debug: bool = False) -> None:
        self._done = False
        self._record_q = multiprocessing.Queue()
        self._result_q = multiprocessing.Queue()
        self._process = multiprocessing.current_process()
        self._settings = self._make_settings()
        self._monitor_pid = pid
        self._debug = debug

        if debug:
            self._settings["log_internal"] = None

        self._interface = wandb.wandb_sdk.interface.interface.BackendSender(
            record_q=self._record_q,
            result_q=self._result_q,
            process=self._process,
            process_check=False,
        )

    def _make_settings(self) -> Dict[str, Any]:
        log_level = logging.DEBUG
        start_time = time.time()
        start_datetime = datetime.datetime.now()
        timespec = datetime.datetime.strftime(start_datetime, "%Y%m%d_%H%M%S")

        wandb_dir = "wandb"
        pid = os.getpid()
        run_path = "run-{}-{}-server".format(timespec, pid)
        run_dir = os.path.join(wandb_dir, run_path)
        files_dir = os.path.join(run_dir, "files")
        sync_file = os.path.join(run_dir, "run-{}.wandb".format(start_time))
        os.makedirs(files_dir)
        # TODO: use a real Settings object
        settings = dict(
            log_internal=os.path.join(run_dir, "internal.log"),
            files_dir=files_dir,
            _start_time=start_time,
            _start_datetime=start_datetime,
            disable_code=None,
            code_program=None,
            save_code=None,
            sync_file=sync_file,
            _internal_queue_timeout=20,
            _internal_check_process=8,
            _disable_meta=True,
            _disable_stats=False,
            git_remote=None,
            program=None,
            resume=None,
            ignore_globs=(),
            offline=None,
            _log_level=log_level,
            run_id=None,
            entity=None,
            project=None,
            run_group=None,
            run_job_type=None,
            run_tags=None,
            run_name=None,
            run_notes=None,
            _jupyter=None,
            _kaggle=None,
            _offline=None,
            email=None,
            silent=None,
        )
        return settings

    def run(self, port: int) -> None:
        try:
            wandb.wandb_sdk.internal.internal.wandb_internal(
                settings=self._settings,
                record_q=self._record_q,
                result_q=self._result_q,
                port=port,
                user_pid=self._monitor_pid,
            )
        except KeyboardInterrupt:
            pass

    def cleanup(self) -> None:
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True
        self._interface.join()


def serve(
    backend: GrpcBackend, port: int, port_filename: str = None, address: str = None
) -> int:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    try:
        wandb_server_pb2_grpc.add_InternalServiceServicer_to_server(
            InternalServiceServicer(server, backend), server
        )
        port = server.add_insecure_port("127.0.0.1:{}".format(port))
        server.start()

        if port_filename:
            dname, bname = os.path.split(port_filename)
            f = tempfile.NamedTemporaryFile(
                prefix=bname, dir=dname, mode="w", delete=False
            )
            tmp_filename = f.name
            try:
                with f:
                    f.write("%d" % port)
                os.rename(tmp_filename, port_filename)
            except Exception:
                os.unlink(tmp_filename)
                raise

        # server.wait_for_termination()
    except KeyboardInterrupt:
        backend.cleanup()
        server.stop(0)
        raise
    except Exception:
        backend.cleanup()
        server.stop(0)
        raise
    return port


def main(
    port: int = None,
    port_filename: str = None,
    address: str = None,
    pid: int = None,
    run: str = None,
    rundir: str = None,
    debug: bool = False,
) -> None:
    if debug:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    backend = GrpcBackend(pid=pid, debug=debug)
    port = serve(backend, port or 0, port_filename=port_filename, address=address)
    setproctitle = wandb.util.get_module("setproctitle")
    if setproctitle:
        setproctitle.setproctitle("wandb_internal[grpc:{}]".format(port))
    backend.run(port=port)
    backend.cleanup()


if __name__ == "__main__":
    main()
