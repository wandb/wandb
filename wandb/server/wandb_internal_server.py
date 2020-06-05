#!/usr/bin/env python
"""WIP wandb grpc server."""

from concurrent import futures
import logging

import grpc
# from wandb.proto import wandb_internal_pb2  # type: ignore
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

    def __init__(self, server):
        self._server = server
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


def serve():
    try:
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        wandb_server_pb2_grpc.add_InternalServiceServicer_to_server(
            InternalServiceServicer(server), server)
        server.add_insecure_port('[::]:50051')
        server.start()
        server.wait_for_termination()
        print("server shutting down")
        print("shutdown")
    except KeyboardInterrupt:
        print("control-c")


if __name__ == '__main__':
    # ds = datastore.DataStore()
    # ds.open("out.dat")
    # fs = dict()
    try:
        logging.basicConfig()
        serve()
    except KeyboardInterrupt:
        print("outer control-c")

    # rfs = fs.get('rfs')
    # if rfs:
    #    rfs.finish(0)
