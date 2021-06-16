#
# -*- coding: utf-8 -*-
"""GRPC router

GRPC router handles requests on a queue and sends them to a grpc server.
"""

from __future__ import print_function

import datetime
import logging
import multiprocessing
import os
import time

import grpc  # type: ignore
import setproctitle  # type: ignore
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2
from wandb.proto import wandb_server_pb2_grpc
from wandb.server import grpc_server  # type: ignore

from . import internal_util


if wandb.TYPE_CHECKING:
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from .settings_static import SettingsStatic
        from typing import Any, Callable, Optional
        from six.moves.queue import Queue
        from wandb.proto.wandb_internal_pb2 import Record, Result
        from wandb.proto.wandb_server_pb2_grpc import InternalServiceStub
        from threading import Event


logger = logging.getLogger(__name__)


def configure_logging(log_fname: str, log_level: int, run_id: str = None) -> None:
    # TODO: we may want make prints and stdout make it into the logs
    # sys.stdout = open(settings.log_internal, "a")
    # sys.stderr = open(settings.log_internal, "a")
    log_handler = logging.FileHandler(log_fname)
    log_handler.setLevel(log_level)

    class WBFilter(logging.Filter):
        def filter(self, record: "Any") -> bool:
            record.run_id = run_id
            return True

    if run_id:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
            "[%(run_id)s:%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
            "[%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
        )

    log_handler.setFormatter(formatter)
    if run_id:
        log_handler.addFilter(WBFilter())
    # If this is called without "wandb", backend logs from this module
    # are not streamed to `debug-internal.log` when we spawn with fork
    # TODO: (cvp) we should really take another pass at logging in general
    root = logging.getLogger("wandb")
    root.propagate = False
    root.setLevel(logging.DEBUG)
    root.addHandler(log_handler)


class InternalGrpcProcess(multiprocessing.Process):
    def __init__(self, record_q, result_q, port, settings, port_q):
        super(InternalGrpcProcess, self).__init__()
        self._record_q = record_q
        self._result_q = result_q
        self._port = port
        self._settings = settings
        self._port_q = port_q

    def run(self):
        local_port_q: "Queue[int]" = multiprocessing.Queue()
        backend = grpc_server.Backend()
        backend.setup(process=self, record_q=self._record_q, result_q=self._result_q)
        _ = grpc_server.serve_async(
            backend=backend, port=self._port, port_q=local_port_q
        )

        port = local_port_q.get(timeout=5)
        if port is None:
            print("ERROR: port not found")
            # TODO error

        setproctitle.setproctitle("wandb_internal[grpc:{}]".format(port))

        try:
            wandb.wandb_sdk.internal.internal.wandb_internal(
                settings=self._settings,
                record_q=self._record_q,
                result_q=self._result_q,
                port=port,
                port_q=self._port_q,
            )
        except KeyboardInterrupt:
            pass


class GrpcRouterThread(internal_util.RecordLoopThread):
    """Reads records from queue and dispatches to grpc-server."""

    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _stopped: "Event"
    _stub: "Optional[InternalServiceStub]"

    def __init__(
        self,
        settings: "SettingsStatic",
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        stopped: "Event",
    ) -> None:
        super(GrpcRouterThread, self).__init__(
            input_record_q=record_q, result_q=result_q, stopped=stopped,
        )
        self.name = "GrpcRouterThread"
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._stopped = stopped
        self._stub = None

    def _setup(self) -> None:
        pass

    def _finish(self) -> None:
        pass

    def route_header(self, record: "Record") -> None:
        pass

    def route_request_check_version(self, record: "Record") -> None:
        result = pb.Result(uuid=record.uuid)
        self._result_q.put(result)

    def route_request_poll_exit(self, record: "Record") -> None:
        result = pb.Result(uuid=record.uuid)
        result.response.poll_exit_response.done = True
        self._result_q.put(result)

    def route_request_get_summary(self, record: "Record") -> None:
        result = pb.Result(uuid=record.uuid)
        self._result_q.put(result)

    def route_request_sampled_history(self, record: "Record") -> None:
        result = pb.Result(uuid=record.uuid)
        self._result_q.put(result)

    def route_request_shutdown(self, record: "Record") -> None:
        result = pb.Result(uuid=record.uuid)
        self._result_q.put(result)
        self._stopped.set()

    def route_request(self, record: "Record") -> None:
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        router_str = "route_request_" + request_type
        router_func: Callable[[Record], None] = getattr(self, router_str, None)
        if request_type != "network_status":
            logger.debug("route_request: {}".format(request_type))
        if not router_func:
            # TODO: figure out why we dont get asserts
            print("unknown route: {}".format(router_str))
        assert router_func, "unknown route: {}".format(router_str)
        router_func(record)

    def route_run(self, data: "Record") -> None:
        # print("DEBUG0", data, self._stub)
        if not self._stub:
            return
        run_result = self._stub.RunUpdate(data.run)

        if data.control.req_resp:
            resp = pb.Result(uuid=data.uuid)
            # TODO: we could do self._interface.publish_defer(resp) to notify
            # the handler not to actually perform server updates for this uuid
            # because the user process will send a summary update when we resume
            resp.run_result.run.CopyFrom(run_result.run)
            # print("SEND run", time.time(), resp)
            self._result_q.put(resp)

    def route_summary(self, data: "Record") -> None:
        pass

    def route_history(self, data: "Record") -> None:
        pass

    def route_output(self, data: "Record") -> None:
        pass

    def route_telemetry(self, data: "Record") -> None:
        pass

    def route_request_run_start(self, data: "Record") -> None:
        resp = pb.Result(uuid=data.uuid)
        self._result_q.put(resp)

    def route_request_stop_status(self, record: "Record") -> None:
        assert record.control.req_resp
        result = pb.Result(uuid=record.uuid)
        status_resp = result.response.stop_status_response
        status_resp.run_should_stop = False
        self._result_q.put(result)

    def route_exit(self, record: "Record") -> None:
        pass

    def route_request_network_status(self, record: "Record") -> None:
        assert record.control.req_resp
        result = pb.Result(uuid=record.uuid)
        self._result_q.put(result)

    def _process(self, record: "Record") -> None:
        # print("DEBUG: process", time.time(), record)
        record_type = record.WhichOneof("record_type")
        assert record_type
        router_str = "route_" + record_type
        router_func: Callable[[Record], None] = getattr(self, router_str, None)
        if not router_func:
            # TODO: figure out why we dont get asserts
            print("unknown route: {}".format(router_str))
        assert router_func, "unknown route: {}".format(router_str)
        router_func(record)

    def _debounce(self) -> None:
        pass

    def _create_settings(self) -> dict:
        log_level = logging.DEBUG
        start_time = time.time()
        start_datetime = datetime.datetime.now()
        timespec = datetime.datetime.strftime(start_datetime, "%Y%m%d_%H%M%S")

        wandb_dir = "wandb"
        run_path = "run-{}-server".format(timespec)
        run_dir = os.path.join(wandb_dir, run_path)
        files_dir = os.path.join(run_dir, "files")
        sync_file = os.path.join(run_dir, "run-{}.wandb".format(start_time))
        os.makedirs(files_dir)
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
            _internal_check_process=0,
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

    def _connect(self, port) -> None:
        channel = grpc.insecure_channel("localhost:{}".format(port))
        stub = wandb_server_pb2_grpc.InternalServiceStub(channel)
        self._stub = stub
        d = wandb_server_pb2.ServerStatusRequest()
        _ = self._stub.ServerStatus(d)

    def _launch_grpc_server(self, port=0) -> None:
        # bind_address = "localhost:{}".format(port)
        record_q: "Queue[Record]" = multiprocessing.Queue()
        result_q: "Queue[Result]" = multiprocessing.Queue()
        port_q: "Queue[int]" = multiprocessing.Queue()

        settings = self._create_settings()

        internal_proc = InternalGrpcProcess(
            port=port,
            settings=settings,
            record_q=record_q,
            result_q=result_q,
            port_q=port_q,
        )
        internal_proc.daemon = True
        internal_proc.name = "wandb_internal"
        internal_proc.start()

        port = port_q.get(timeout=5)
        if port is None:
            print("ERROR: couldnt spawn grpc server quick enough")
            # TODO: raise error?

        self._connect(port)
        # TODO: verify started before exiting context
        # print("DEBUG: done_launch", time.time())
