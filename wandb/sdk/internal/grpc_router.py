#
# -*- coding: utf-8 -*-
"""GRPC router

GRPC router handles requests on a queue and sends them to a grpc server.
"""

from __future__ import print_function

import contextlib
import datetime
import logging
import multiprocessing
import os
import socket
import time

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.server import grpc_server  # type: ignore

from . import internal_util


if wandb.TYPE_CHECKING:
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from .settings_static import SettingsStatic
        from typing import Any, Callable
        from six.moves.queue import Queue
        from multiprocessing import Process
        from wandb.proto.wandb_internal_pb2 import Record, Result
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


def _run_server(bind_address, port, process):
    """Start a server in a subprocess."""
    print("start serve")
    # setproctitle.setproctitle("python grpcserver")
    try:
        logging.basicConfig()
        backend = grpc_server.Backend()

        backend.setup(process=process)
        grpc_server.serve(backend, port)
    except KeyboardInterrupt:
        print("outer control-c")
    print("done serve")


@contextlib.contextmanager
def _reserve_port():
    """Find and reserve a port for all subprocesses to use."""
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    if sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 0:
        raise RuntimeError("Failed to set SO_REUSEPORT.")
    sock.bind(("", 0))
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


class GrpcRouterThread(internal_util.RecordLoopThread):
    """Reads records from queue and dispatches to grpc-server."""

    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _stopped: "Event"

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

    def _setup(self) -> None:
        pass

    def _finish(self) -> None:
        pass

    def route_header(self, record: "Record") -> None:
        pass

    def route_request_check_version(self, record: "Record") -> None:
        pass

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
        print("DEBUG0")
        run = data.run
        print("DEBUG1", data)

        if data.control.req_resp:
            print("DEBUG1a", run)
            resp = pb.Result(uuid=data.uuid)
            print("DEBUG1b", run)
            # TODO: we could do self._interface.publish_defer(resp) to notify
            # the handler not to actually perform server updates for this uuid
            # because the user process will send a summary update when we resume
            resp.run_result.run.CopyFrom(run)
            print("DEBUG2", resp)
            self._result_q.put(resp)
        print("DEBUG3")

    def route_summary(self, data: "Record") -> None:
        pass

    def route_history(self, data: "Record") -> None:
        pass

    def route_output(self, data: "Record") -> None:
        pass

    def route_telemetry(self, data: "Record") -> None:
        pass

    def route_request_run_start(self, data: "Record") -> None:
        pass

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
        print("DEBUG: process", record)
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

    def _create_internal(self) -> "Process":
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

        record_q: "Queue[Record]" = multiprocessing.Queue()
        result_q: "Queue[Result]" = multiprocessing.Queue()

        internal_proc = multiprocessing.Process(
            target=wandb.wandb_sdk.internal.internal.wandb_internal,
            kwargs=dict(settings=settings, record_q=record_q, result_q=result_q,),
        )
        internal_proc.daemon = True
        internal_proc.name = "wandb_internal"
        return internal_proc

    def _launch_grpc_server(self) -> None:
        print("launch")
        with _reserve_port() as port:
            print("GOT", port)
            bind_address = "localhost:{}".format(port)
            internal_proc = self._create_internal()
            internal_proc.start()
            worker = multiprocessing.Process(
                target=_run_server, args=(bind_address, port, internal_proc)
            )
            worker.daemon = True
            worker.start()
            # TODO: verify started before exiting context
        print("done_launch")
