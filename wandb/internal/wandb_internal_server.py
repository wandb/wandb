#!/usr/bin/env python
"""The Python implementation of the gRPC route guide server."""

from concurrent import futures
import logging
import grpc
import json

import wandb_internal_pb2
import wandb_internal_pb2_grpc


def log(data):
    d = json.loads(data.json)
    return wandb_internal_pb2.LogResult()


class InternalServiceServicer(wandb_internal_pb2_grpc.InternalServiceServicer):
    """Provides methods that implement functionality of route guide server."""

    def __init__(self, server):
        self._server = server

    def Log(self, request, context):
        d = json.loads(request.json)
        result = wandb_internal_pb2.LogResult()
        return result

    def ServerShutdown(self, request, context):
        result = wandb_internal_pb2.ServerShutdownResult()
        self._server.stop(5)
        return result

    def ServerStatus(self, request, context):
        result = wandb_internal_pb2.ServerStatusResult()
        return result

    def RunGet(self, request, context):
        result = wandb_internal_pb2.RunGetResult()
        return result

    def RunUpdate(self, request, context):
        result = wandb_internal_pb2.RunUpdateResult()
        return result


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    wandb_internal_pb2_grpc.add_InternalServiceServicer_to_server(
        InternalServiceServicer(server), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    server.wait_for_termination()
    print("server shutting down")


if __name__ == '__main__':
    logging.basicConfig()
    serve()
