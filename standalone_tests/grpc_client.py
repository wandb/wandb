#!/usr/bin/env python
"""WIP wandb grpc test client."""

from __future__ import print_function

import json
import logging
import time

import grpc
import six
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.proto import wandb_server_pb2  # type: ignore
from wandb.proto import wandb_server_pb2_grpc  # type: ignore


def make_exit_data(data):
    edata = wandb_internal_pb2.ExitData()
    edata.exit_code = data.get("exit_code", 0)
    return edata


def make_log_data(data):
    hdata = wandb_internal_pb2.HistoryData()
    for k, v in data.items():
        item = hdata.item.add()
        item.key = k
        item.value_json = json.dumps(v)
    return hdata


def make_config(config_dict, obj=None):
    config = obj or wandb_internal_pb2.ConfigData()
    for k, v in six.iteritems(config_dict):
        update = config.update.add()
        update.key = k
        update.value_json = json.dumps(v)
    return config


def make_run_data(data):
    rdata = wandb_internal_pb2.RunData()
    config_dict = data.get("config")
    if config_dict:
        make_config(config_dict, obj=rdata.config)
    return rdata


class WandbInternalClient(object):
    def __init__(self):
        self._channel = None
        self._stub = None

    def connect(self):
        channel = grpc.insecure_channel("localhost:50051")
        stub = wandb_server_pb2_grpc.InternalServiceStub(channel)
        self._channel = channel
        self._stub = stub

    def run_update(self, data):
        req = make_run_data(data)
        run = self._stub.RunUpdate(req)
        return run

    def log(self, data):
        req = make_log_data(data)
        _ = self._stub.Log(req)

    def exit(self, data):
        req = make_exit_data(data)
        _ = self._stub.RunExit(req)

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

    run_result = wic.run_update(dict(config=dict(parm1=2, param2=3)))
    run = run_result.run
    base_url = "https://app.wandb.ai"
    print(
        "Monitor your run ({}) at: {}/{}/{}/runs/{}".format(
            run.display_name, base_url, run.entity, run.project, run.run_id
        )
    )
    wic.log(dict(this=2, _step=1))
    wic.log(dict(this=3, _step=2))
    wic.log(dict(this=4, _step=3))
    time.sleep(2)
    print(
        "Your run ({}) is complete: {}/{}/{}/runs/{}".format(
            run.display_name, base_url, run.entity, run.project, run.run_id
        )
    )
    wic.exit(dict(exit_code=0))

    wic.shutdown()


if __name__ == "__main__":
    logging.basicConfig()
    main()
