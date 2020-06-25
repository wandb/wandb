#!/usr/bin/env python
"""WIP wandb grpc server."""

from concurrent import futures
import datetime
import logging
import multiprocessing
import time

import grpc
from wandb.interface import constants
from wandb.internal.internal import wandb_internal
from wandb.proto import wandb_server_pb2  # type: ignore
from wandb.proto import wandb_server_pb2_grpc  # type: ignore


# from wandb.apis import internal
# from wandb.apis import file_stream

# api = internal.Api()
# settings=dict(entity="jeff", project="uncategorized")

# def log(data):
#    d = json.loads(data.json)
#    return wandb_internal_pb2.LogResult()
#


class InternalServiceServicer(wandb_server_pb2_grpc.InternalServiceServicer):
    """Provides methods that implement functionality of route guide server."""

    def __init__(self, server, backend):
        self._server = server
        self._backend = backend
        # self._ds = ds
        # self._fs = fs
        pass

    def Log(self, request, context):  # noqa: N802
        # self._ds.write(request)
        # d = json.loads(request.json)
        # fs = self._fs.get('rfs')
        # if fs:
        #     #print("dump", json.dumps(d))
        #     #fs = file_stream.FileStreamApi(api, run_id, settings=settings)
        #     #fs.start()
        #     x = fs.push("wandb-history.jsonl", json.dumps(d))
        #     #fs.finish(0)
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

    # def RunGet(self, request, context):
    #     result = wandb_internal_pb2.RunGetResult()
    #     return result

    # def RunUpdate(self, request, context):
    #     run = request.run
    #     self._ds.write(run)

    #    config = json.loads(run.config_json)

    #    r = api.upsert_run(name=run.run_id, config=config, **settings)
    #    fs = file_stream.FileStreamApi(api, run.run_id, settings=settings)
    #    fs.start()
    #    self._fs['rfs'] = fs
    #    self._fs['run_id'] = run.run_id

    #    result = wandb_internal_pb2.RunUpdateResult()
    #    return result


# TODO(jhr): this should be merged with code in backend/backend.py ensure launched
class Backend:
    def __init__(self):
        self._done = False

    def setup(self):
        log_level = logging.DEBUG
        settings = dict(
            log_internal="internal.log",
            files_dir=".",
            _start_time=time.time(),
            _start_datetime=datetime.datetime.now(),
            disable_code=None,
            code_program=None,
            save_code=None,
            sync_file="run-{}.wandb".format(time.time()),
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


if __name__ == "__main__":
    # ds = datastore.DataStore()
    # ds.open("out.dat")
    # fs = dict()
    try:
        logging.basicConfig()
        backend = Backend()
        backend.setup()
        serve(backend)
    except KeyboardInterrupt:
        print("outer control-c")

    # rfs = fs.get('rfs')
    # if rfs:
    #    rfs.finish(0)
