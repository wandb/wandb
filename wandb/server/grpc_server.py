#!/usr/bin/env python
"""WIP wandb grpc server."""

from concurrent import futures
import datetime
import logging
import multiprocessing
import os
import time

import grpc
from wandb.interface import constants, interface
from wandb.internal.internal import wandb_internal
from wandb.lib import runid
from wandb.proto import wandb_server_pb2  # type: ignore
from wandb.proto import wandb_server_pb2_grpc  # type: ignore


class InternalServiceServicer(wandb_server_pb2_grpc.InternalServiceServicer):
    """Provides methods that implement functionality of route guide server."""

    def __init__(self, server, backend):
        self._server = server
        self._backend = backend

    def RunUpdate(self, run_data, context):  # noqa: N802
        if not run_data.run_id:
            run_data.run_id = runid.generate_id()
        run = self._backend._interface._send_run_sync(run_data)
        result = wandb_server_pb2.RunUpdateResult(run=run.run)
        return result

    def RunExit(self, exit_data, context):  # noqa: N802
        _ = self._backend._interface._send_exit_sync(exit_data)
        result = wandb_server_pb2.RunExitResult()
        return result

    def Log(self, log_data, context):  # noqa: N802
        self._backend._interface._send_history(log_data)
        result = wandb_server_pb2.LogResult()
        return result

    def ServerShutdown(self, request, context):  # noqa: N802
        self._backend.cleanup()
        result = wandb_server_pb2.ServerShutdownResult()
        self._server.stop(5)
        return result

    def ServerStatus(self, request, context):  # noqa: N802
        result = wandb_server_pb2.ServerStatusResult()
        return result


# TODO(jhr): this should be merged with code in backend/backend.py ensure launched
class Backend:
    def __init__(self):
        self._done = False

    def setup(self):
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
            _disable_stats=True,
        )

        mp = multiprocessing
        fd_pipe_child, fd_pipe_parent = mp.Pipe()

        process_queue = mp.Queue()
        # TODO: should this be one item just to make sure it stays fully synchronous?
        req_queue = mp.Queue()
        resp_queue = mp.Queue()
        cancel_queue = mp.Queue()
        notify_queue = mp.Queue()
        use_redirect = True

        wandb_process = mp.Process(
            target=wandb_internal,
            args=(
                settings,
                notify_queue,
                process_queue,
                req_queue,
                resp_queue,
                cancel_queue,
                fd_pipe_child,
                log_level,
                use_redirect,
            ),
        )
        wandb_process.name = "wandb_internal"
        wandb_process.start()

        self.wandb_process = wandb_process
        self.notify_queue = notify_queue

        self._interface = interface.BackendSender(
            process_queue=process_queue,
            notify_queue=notify_queue,
            request_queue=req_queue,
            response_queue=resp_queue,
            process=wandb_process,
        )

    def cleanup(self):
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True

        self.notify_queue.put(constants.NOTIFY_SHUTDOWN)
        # TODO: make sure this is last in the queue?  lock?
        self.notify_queue.close()
        self.wandb_process.join()
        # No printing allowed from here until redirect restore!!!


def serve(backend):
    try:
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        wandb_server_pb2_grpc.add_InternalServiceServicer_to_server(
            InternalServiceServicer(server, backend), server
        )
        server.add_insecure_port("[::]:50051")
        server.start()
        server.wait_for_termination()
        print("server shutting down")
        print("shutdown")
    except KeyboardInterrupt:
        print("control-c")


def main():
    try:
        logging.basicConfig()
        backend = Backend()
        backend.setup()
        serve(backend)
    except KeyboardInterrupt:
        print("outer control-c")


if __name__ == "__main__":
    main()
