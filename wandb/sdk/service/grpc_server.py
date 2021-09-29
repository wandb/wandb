#!/usr/bin/env python
"""wandb grpc server.

- GrpcServer:
- StreamMux:
- StreamRecord:
- WandbServicer:

"""

from concurrent import futures
import datetime
import logging
import multiprocessing
import os
import sys
import tempfile
import threading
from threading import Event
import time
from typing import Any, Callable, Dict, List, Optional
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


def _make_settings() -> Dict[str, Any]:
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


class StreamThread(threading.Thread):
    """Class to running internal process as a thread."""

    def __init__(self, target: Callable, kwargs: Dict[str, Any]) -> None:
        threading.Thread.__init__(self)
        self._target = target
        self._kwargs = kwargs
        self.daemon = True
        self.pid = 0

    def run(self) -> None:
        self._target(**self._kwargs)


class StreamRecord:
    _record_q: "queue.Queue[pb.Record]"
    _result_q: "queue.Queue[pb.Result]"
    _iface: interface.BackendSender
    _thread: StreamThread

    def __init__(self) -> None:
        self._record_q = multiprocessing.Queue()
        self._result_q = multiprocessing.Queue()
        process = multiprocessing.current_process()
        self._iface = interface.BackendSender(
            record_q=self._record_q,
            result_q=self._result_q,
            process=process,
            process_check=False,
        )

    def start_thread(self, thread: StreamThread) -> None:
        self._thread = thread
        thread.start()
        self._wait_thread_active()

    def _wait_thread_active(self) -> None:
        result = self._iface.communicate_status()
        assert result

    def join(self) -> None:
        self._iface.join()
        if self._thread:
            self._thread.join()

    @property
    def interface(self) -> interface.BackendSender:
        return self._iface


class StreamAction:
    _action: str
    _stream_id: str
    _processed: Event
    _data: Any

    def __init__(self, action: str, stream_id: str, data: Any = None):
        self._action = action
        self._stream_id = stream_id
        self._data = data
        self._processed = Event()

    def wait_handled(self) -> None:
        self._processed.wait()

    def set_handled(self) -> None:
        self._processed.set()


class StreamMux:
    _streams_lock: threading.Lock
    _streams: Dict[str, StreamRecord]
    _port: Optional[int]
    _pid: Optional[int]
    _action_q: "queue.Queue[StreamAction]"
    _stopped: Event

    def __init__(self) -> None:
        self._streams_lock = threading.Lock()
        self._streams = dict()
        self._port = None
        self._pid = None
        self._stopped = Event()
        self._action_q = queue.Queue()

    def set_port(self, port: int) -> None:
        self._port = port

    def set_pid(self, pid: int) -> None:
        self._pid = pid

    def add_stream(self, stream_id: str) -> None:
        action = StreamAction(action="add", stream_id=stream_id)
        self._action_q.put(action)
        action.wait_handled()

    def del_stream(self, stream_id: str) -> None:
        action = StreamAction(action="del", stream_id=stream_id)
        self._action_q.put(action)
        action.wait_handled()

    def teardown(self, exit_code: int) -> None:
        action = StreamAction(action="teardown", stream_id="na", data=exit_code)
        self._action_q.put(action)
        action.wait_handled()

    def stream_names(self) -> List[str]:
        with self._streams_lock:
            names = list(self._streams.keys())
            return names

    def has_stream(self, stream_id: str) -> bool:
        with self._streams_lock:
            return stream_id in self._streams

    def get_stream(self, stream_id: str) -> StreamRecord:
        with self._streams_lock:
            stream = self._streams[stream_id]
            return stream

    def _process_add(self, action: StreamAction) -> None:
        stream = StreamRecord()
        settings = _make_settings()
        thread = StreamThread(
            target=wandb.wandb_sdk.internal.internal.wandb_internal,
            kwargs=dict(
                settings=settings,
                record_q=stream._record_q,
                result_q=stream._result_q,
                port=self._port,
                user_pid=self._pid,
            ),
        )
        stream.start_thread(thread)
        with self._streams_lock:
            self._streams[action._stream_id] = stream

    def _process_del(self, action: StreamAction) -> None:
        with self._streams_lock:
            stream = self._streams.pop(action._stream_id)
        stream.join()

    def _finish_all(self, streams: Dict[str, StreamRecord], exit_code: int) -> None:
        if not streams:
            return

        for sid, stream in streams.items():
            wandb.termlog(f"Finishing run: {sid}...")  # type: ignore
            stream.interface.publish_exit(exit_code)

        while streams:
            for sid, stream in list(streams.items()):
                poll_exit_resp = stream.interface.communicate_poll_exit()
                if poll_exit_resp and poll_exit_resp.done:
                    streams.pop(sid)
                time.sleep(0.1)
        wandb.termlog("Done!")  # type: ignore

    def _process_teardown(self, action: StreamAction) -> None:
        exit_code: int = action._data
        # TODO: find any running streams and shut them down
        with self._streams_lock:
            streams_copy = self._streams.copy()
            self._streams = dict()
        self._finish_all(streams_copy, exit_code)
        self._stopped.set()

    def _process_action(self, action: StreamAction) -> None:
        if action._action == "add":
            self._process_add(action)
            return
        if action._action == "del":
            self._process_del(action)
            return
        if action._action == "teardown":
            self._process_teardown(action)
            return
        raise AssertionError(f"Unsupported action: {action._action}")

    def loop(self) -> None:
        while not self._stopped.is_set():
            # TODO: check for parent process going away
            try:
                action = self._action_q.get(timeout=1)
            except queue.Empty:
                continue
            self._process_action(action)
            action.set_handled()
            self._action_q.task_done()

    def cleanup(self) -> None:
        pass


class WandbServicer(wandb_server_pb2_grpc.InternalServiceServicer):
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
        request: wandb_server_pb2.ServerShutdownRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerShutdownResponse:
        result = wandb_server_pb2.ServerShutdownResponse()
        self._server.stop(5)
        return result

    def ServerStatus(  # noqa: N802
        self,
        request: wandb_server_pb2.ServerStatusRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerStatusResponse:
        result = wandb_server_pb2.ServerStatusResponse()
        return result

    def ServerInformInit(  # noqa: N802
        self,
        request: wandb_server_pb2.ServerInformInitRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerInformInitResponse:
        stream_id = request._info.stream_id
        self._mux.add_stream(stream_id)
        result = wandb_server_pb2.ServerInformInitResponse()
        return result

    def ServerInformFinish(  # noqa: N802
        self,
        request: wandb_server_pb2.ServerInformFinishRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerInformFinishResponse:
        stream_id = request._info.stream_id
        self._mux.del_stream(stream_id)
        result = wandb_server_pb2.ServerInformFinishResponse()
        return result

    def ServerInformTeardown(  # noqa: N802
        self,
        request: wandb_server_pb2.ServerInformTeardownRequest,
        context: grpc.ServicerContext,
    ) -> wandb_server_pb2.ServerInformTeardownResponse:
        exit_code = request.exit_code
        self._mux.teardown(exit_code)
        result = wandb_server_pb2.ServerInformTeardownResponse()
        return result


class GrpcServer:
    def __init__(
        self,
        port: int = None,
        port_fname: str = None,
        address: str = None,
        pid: int = None,
        debug: bool = False,
    ) -> None:
        self._port = port
        self._port_fname = port_fname
        self._address = address
        self._pid = pid
        self._debug = debug
        debug = True
        if debug:
            logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    def _inform_used_port(self, port: int) -> None:
        if not self._port_fname:
            return
        dname, bname = os.path.split(self._port_fname)
        f = tempfile.NamedTemporaryFile(prefix=bname, dir=dname, mode="w", delete=False)
        tmp_filename = f.name
        try:
            with f:
                f.write("%d" % port)
            os.rename(tmp_filename, self._port_fname)
        except Exception:
            os.unlink(tmp_filename)
            raise

    def _launch(self, mux: StreamMux) -> int:
        address: str = self._address or "127.0.0.1"
        port: int = self._port or 0
        pid: int = self._pid or 0
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        servicer = WandbServicer(server=server, mux=mux)
        try:
            wandb_server_pb2_grpc.add_InternalServiceServicer_to_server(
                servicer, server
            )
            port = server.add_insecure_port(f"{address}:{port}")
            mux.set_port(port)
            mux.set_pid(pid)
            server.start()
            self._inform_used_port(port)
        except KeyboardInterrupt:
            mux.cleanup()
            server.stop(0)
            raise
        except Exception:
            mux.cleanup()
            server.stop(0)
            raise
        return port

    def serve(self) -> None:
        mux = StreamMux()
        port = self._launch(mux=mux)
        setproctitle = wandb.util.get_optional_module("setproctitle")
        if setproctitle:
            setproctitle.setproctitle("wandb_internal[grpc:{}]".format(port))
        mux.loop()
