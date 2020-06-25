#!/usr/bin/env python
"""WIP wandb grpc test client."""

from __future__ import print_function

import json
import logging

import grpc
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.proto import wandb_server_pb2  # type: ignore
from wandb.proto import wandb_server_pb2_grpc  # type: ignore


def make_log_data(data):
    hdata = wandb_internal_pb2.HistoryData()
    for k, v in data.items():
        item = hdata.item.add()
        item.key = k
        item.value_json = json.dumps(v)
    return hdata


class WandbInternalClient(object):
    def __init__(self):
        self._channel = None
        self._stub = None

    def connect(self):
        channel = grpc.insecure_channel("localhost:50051")
        stub = wandb_server_pb2_grpc.InternalServiceStub(channel)
        self._channel = channel
        self._stub = stub

    def log(self, data):
        req = make_log_data(data)
        _ = self._stub.Log(req)

    def status(self):
        req = wandb_server_pb2.ServerStatusRequest()
        _ = self._stub.ServerStatus(req)

    def shutdown(self):
        req = wandb_server_pb2.ServerShutdownRequest()
        _ = self._stub.ServerShutdown(req)

    # def run_get(self, run_id):
    #     req = wandb_internal_pb2.RunGetRequest(id=run_id)
    #     result = self._stub.RunGet(req)
    #     return result

    # def run_update(self, run_dict):
    #    run = wandb_internal_pb2.Run()
    #    run.run_id = run_dict['run_id']
    #    run.config_json = json.dumps(run_dict.get('config', {}))
    #    req = wandb_internal_pb2.RunUpdateRequest(run=run)
    #    result = self._stub.RunUpdate(req)
    #    return result


def main():
    wic = WandbInternalClient()
    wic.connect()

    # run_id = "run1"
    # res = wic.run_get(run_id)
    # print("runget:", res)
    # res = wic.run_update(res.run)
    # print("run:", res)
    wic.log(dict(this="that"))
    wic.shutdown()


if __name__ == "__main__":
    logging.basicConfig()
    main()
