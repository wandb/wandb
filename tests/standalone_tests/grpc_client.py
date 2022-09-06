#!/usr/bin/env python
"""WIP wandb grpc test client.

This is a very internal test client, it is only for testing to verify base functionality is preserved.

"""


import datetime
import enum
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Dict

import grpc
import wandb
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.proto import wandb_server_pb2_grpc  # type: ignore
from wandb.proto import wandb_server_pb2 as spb  # type: ignore

if TYPE_CHECKING:
    from google.protobuf.internal.containers import MessageMap


def make_exit_data(data):
    edata = wandb_internal_pb2.RunExitRecord()
    edata.exit_code = data.get("exit_code", 0)
    return edata


def make_log_data(data):
    hdata = wandb_internal_pb2.HistoryRecord()
    for k, v in data.items():
        item = hdata.item.add()
        item.key = k
        item.value_json = json.dumps(v)
    return hdata


def make_config(config_dict, obj=None):
    config = obj or wandb_internal_pb2.ConfigRecord()
    for k, v in config_dict.items():
        update = config.update.add()
        update.key = k
        update.value_json = json.dumps(v)
    return config


def _pbmap_apply_dict(
    m: "MessageMap[str, spb.SettingsValue]", d: Dict[str, Any]
) -> None:
    for k, v in d.items():
        if isinstance(v, datetime.datetime):
            continue
        if isinstance(v, enum.Enum):
            continue
        sv = spb.SettingsValue()
        if v is None:
            sv.null_value = True
        elif isinstance(v, int):
            sv.int_value = v
        elif isinstance(v, float):
            sv.float_value = v
        elif isinstance(v, str):
            sv.string_value = v
        elif isinstance(v, bool):
            sv.bool_value = v
        elif isinstance(v, tuple):
            sv.tuple_value.string_values.extend(v)
        m[k].CopyFrom(sv)


def make_settings(settings_dict, obj):
    _pbmap_apply_dict(obj, settings_dict)


def make_run_data(data):
    rdata = wandb_internal_pb2.RunRecord()
    run_id = data.get("run_id")
    if run_id:
        rdata.run_id = run_id
    entity = data.get("entity")
    if entity:
        rdata.entity = entity
    project = data.get("project")
    if project:
        rdata.project = project
    run_group = data.get("group")
    if run_group:
        rdata.run_group = run_group
    job_type = data.get("job_type")
    if job_type:
        rdata.job_type = job_type
    config_dict = data.get("config")
    config_dict = data.get("config")
    if config_dict:
        make_config(config_dict, obj=rdata.config)
    return rdata


def make_summary(summary_dict, obj=None):
    summary = obj or wandb_internal_pb2.SummaryRecord()
    for k, v in summary_dict.items():
        update = summary.update.add()
        update.key = k
        update.value_json = json.dumps(v)
    return summary


def make_output(name, data):
    if name == "stdout":
        otype = wandb_internal_pb2.OutputRecord.OutputType.STDOUT
    elif name == "stderr":
        otype = wandb_internal_pb2.OutputRecord.OutputType.STDERR
    else:
        # TODO(jhr): throw error?
        print("unknown type")
    outdata = wandb_internal_pb2.OutputRecord(output_type=otype, line=data)
    outdata.timestamp.GetCurrentTime()
    return outdata


class WandbInternalClient:
    def __init__(self):
        self._channel = None
        self._stub = None
        self._stream_id = None

    def connect(self):
        channel = grpc.insecure_channel("localhost:50051")
        stub = wandb_server_pb2_grpc.InternalServiceStub(channel)
        self._channel = channel
        self._stub = stub

    def _apply_stream(self, obj):
        assert self._stream_id
        obj._info.stream_id = self._stream_id

    def _inform_init(self, settings):
        # only do this once
        if self._stream_id:
            return
        run_id = settings.run_id
        assert run_id
        self._stream_id = run_id

        settings_dict = dict(settings)
        settings_dict["_log_level"] = logging.DEBUG

        req = spb.ServerInformInitRequest()
        make_settings(settings_dict, req._settings_map)
        self._apply_stream(req)
        _ = self._stub.ServerInformInit(req)

    def run_start(self, run_id):
        settings = wandb.Settings()
        settings._set_run_start_time()
        settings.update(run_id=run_id)
        files_dir = settings.files_dir
        os.makedirs(files_dir)
        log_user = settings.log_user
        os.makedirs(log_user)
        self._inform_init(settings)

    def run_update(self, data):
        req = make_run_data(data)
        self._apply_stream(req)
        run = self._stub.RunUpdate(req)
        return run

    def log(self, data):
        req = make_log_data(data)
        self._apply_stream(req)
        _ = self._stub.Log(req)

    def config(self, data):
        req = make_config(data)
        self._apply_stream(req)
        _ = self._stub.Config(req)

    def summary(self, data):
        req = make_summary(data)
        self._apply_stream(req)
        _ = self._stub.Summary(req)

    def output(self, outtype, data):
        req = make_output(outtype, data)
        self._apply_stream(req)
        _ = self._stub.Output(req)

    def exit(self, data):
        req = make_exit_data(data)
        self._apply_stream(req)
        _ = self._stub.RunExit(req)

    def server_status(self):
        req = spb.ServerStatusRequest()
        _ = self._stub.ServerStatus(req)

    def server_shutdown(self):
        req = spb.ServerShutdownRequest()
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

    def_id = "junk123"
    run_id = os.environ.get("WANDB_RUN_ID", def_id)
    entity = os.environ.get("WANDB_ENTITY")  # noqa: F841
    project = os.environ.get("WANDB_PROJECT")
    group = os.environ.get("WANDB_RUN_GROUP")
    job_type = os.environ.get("WANDB_JOB_TYPE")

    run_data = dict(
        run_id=run_id,
        project=project,
        group=group,
        job_type=job_type,
        config=dict(parm1=2, param2=3),
    )
    wic.run_start(run_id)
    run_result = wic.run_update(run_data)
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
    wic.config(dict(parm5=55, parm6=66))
    wic.summary(dict(sum2=4, sum3=3))
    wic.output("stdout", "Hello world\n")
    wic.output("stderr", "I am an error\n")
    print("delay for 30 seconds...")
    time.sleep(30)
    print(
        "Your run ({}) is complete: {}/{}/{}/runs/{}".format(
            run.display_name, base_url, run.entity, run.project, run.run_id
        )
    )
    wic.exit(dict(exit_code=0))

    wic.server_shutdown()


if __name__ == "__main__":
    logging.basicConfig()
    main()
