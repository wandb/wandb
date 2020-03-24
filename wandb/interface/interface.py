# -*- coding: utf-8 -*-
"""Backend Sender - Send to internal process

Manage backend sender.

"""

import json
from six.moves import queue
import logging
from datetime import date, datetime
import time

from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.interface import constants

import numpy as np  # type: ignore

logger = logging.getLogger("wandb")


def is_numpy_array(obj):
    return np and isinstance(obj, np.ndarray)


def is_tf_tensor(obj):
    import tensorflow
    return isinstance(obj, tensorflow.Tensor)


def is_tf_tensor_typename(typename):
    return typename.startswith('tensorflow.') and ('Tensor' in typename or 'Variable' in typename)


def is_tf_eager_tensor_typename(typename):
    return typename.startswith('tensorflow.') and ('EagerTensor' in typename)


def is_pytorch_tensor(obj):
    import torch
    return isinstance(obj, torch.Tensor)


def is_pytorch_tensor_typename(typename):
    return typename.startswith('torch.') and ('Tensor' in typename or 'Variable' in typename)


def get_full_typename(o):
    """We determine types based on type names so we don't have to import
    (and therefore depend on) PyTorch, TensorFlow, etc.
    """
    instance_name = o.__class__.__module__ + "." + o.__class__.__name__
    if instance_name in ["builtins.module", "__builtin__.module"]:
        return o.__name__
    else:
        return instance_name


def json_friendly(obj):
    """Convert an object into something that's more becoming of JSON"""
    converted = True
    typename = get_full_typename(obj)

    if is_tf_eager_tensor_typename(typename):
        obj = obj.numpy()
    elif is_tf_tensor_typename(typename):
        obj = obj.eval()
    elif is_pytorch_tensor_typename(typename):
        try:
            if obj.requires_grad:
                obj = obj.detach()
        except AttributeError:
            pass  # before 0.4 is only present on variables

        try:
            obj = obj.data
        except RuntimeError:
            pass  # happens for Tensors before 0.4

        if obj.size():
            obj = obj.numpy()
        else:
            return obj.item(), True
    if is_numpy_array(obj):
        if obj.size == 1:
            obj = obj.flatten()[0]
        elif obj.size <= 32:
            obj = obj.tolist()
    elif np and isinstance(obj, np.generic):
        obj = obj.item()
    elif isinstance(obj, bytes):
        obj = obj.decode('utf-8')
    elif isinstance(obj, (datetime, date)):
        obj = obj.isoformat()
    else:
        converted = False
    #if getsizeof(obj) > VALUE_BYTES_LIMIT:
    #    wandb.termwarn("Serializing object of type {} that is {} bytes".format(type(obj).__name__, getsizeof(obj)))

    return obj, converted


class WandBJSONEncoder(json.JSONEncoder):
    """A JSON Encoder that handles some extra types."""

    def default(self, obj):
        if hasattr(obj, 'json_encode'):
            return obj.json_encode()
        if hasattr(obj, 'to_json'):
            return obj.to_json()
        tmp_obj, converted = json_friendly(obj)
        if converted:
            return tmp_obj
        return json.JSONEncoder.default(self, obj)


class BackendSender(object):

    class ExceptionTimeout(Exception):
        pass

    def __init__(self, process_queue=None, notify_queue=None, request_queue=None, response_queue=None):
        self.process_queue = process_queue
        self.notify_queue = notify_queue
        self.request_queue = request_queue
        self.response_queue = response_queue

    def send_output(self, name, data):
        # from vendor.protobuf import google3.protobuf.timestamp
        #ts = timestamp.Timestamp()
        #ts.GetCurrentTime()
        #now = datetime.now()
        if name == "stdout":
            otype = wandb_internal_pb2.OutputData.OutputType.STDOUT
        elif name == "stderr":
            otype = wandb_internal_pb2.OutputData.OutputType.STDERR
        else:
            # FIXME: throw error?
            print("unknown type")
        o = wandb_internal_pb2.OutputData(output_type=otype, str=data)
        o.timestamp.GetCurrentTime()
        rec = wandb_internal_pb2.Record()
        rec.output.CopyFrom(o)
        self.process_queue.put(rec)
        self.notify_queue.put(constants.NOTIFY_PROCESS)

    def send_log(self, data):
        json_data = json.dumps(data, cls=WandBJSONEncoder)
        #json_data = json.dumps(data)
        l = wandb_internal_pb2.LogData(json=json_data)
        rec = wandb_internal_pb2.Record()
        rec.log.CopyFrom(l)
        self.process_queue.put(rec)
        self.notify_queue.put(constants.NOTIFY_PROCESS)

    def _make_run(self, run_dict):
        run = wandb_internal_pb2.Run()
        run.run_id = run_dict['run_id']
        run.config_json = json.dumps(run_dict.get('config', {}))
        return run

    def _make_config(self, config_dict):
        config = wandb_internal_pb2.ConfigData()
        config.run_id = config_dict['run_id']
        config.config_json = json.dumps(config_dict['data'])
        return config

    def _make_stats(self, stats_dict):
        stats = wandb_internal_pb2.StatsData()
        #config.run_id = config_dict['run_id']
        stats.stats_json = json.dumps(stats_dict['data'])
        return stats

    def _make_summary(self, summary_dict):
        json_data = json.dumps(summary_dict['data'], cls=WandBJSONEncoder)
        summary = wandb_internal_pb2.SummaryData()
        summary.run_id = summary_dict['run_id']
        summary.summary_json = json_data
        return summary

    def _make_files(self, files_dict):
        files = wandb_internal_pb2.FilesData()
        for path in files_dict['files']:
            f = files.files.add()
            f.name = path
        return files

    def _make_record(self, run=None, config=None, files=None, summary=None, stats=None):
        rec = wandb_internal_pb2.Record()
        if run:
            rec.run.CopyFrom(run)
        if config:
            rec.config.CopyFrom(config)
        if summary:
            rec.summary.CopyFrom(summary)
        if files:
            rec.files.CopyFrom(files)
        if stats:
            rec.stats.CopyFrom(stats)
        return rec

    def _queue_process(self, rec):
        self.process_queue.put(rec)
        self.notify_queue.put(constants.NOTIFY_PROCESS)

    def _request_flush(self):
        # TODO: make sure request queue is cleared
        # probably need to send a cancel message and
        # wait for it to come back
        pass

    def _request_response(self, rec, timeout=5):
        # TODO: make sure this is called from main process.
        # can only be one outstanding
        # add a cancel queue
        rec.control.req_resp = True
        self.request_queue.put(rec)
        self.notify_queue.put(constants.NOTIFY_REQUEST)

        try:
            rsp = self.response_queue.get(timeout=timeout)
        except queue.Empty:
            self._request_flush()
            raise BackendSender.ExceptionTimeout("timeout")

        # returns response, err
        return rsp

    def send_run(self, run_dict):
        run = self._make_run(run_dict)
        rec = self._make_record(run=run)
        self._queue_process(rec)

    def send_config(self, config_dict):
        cfg = self._make_config(config_dict)
        rec = self._make_record(config=cfg)
        self._queue_process(rec)

    def send_summary(self, summary_dict):
        summary = self._make_summary(summary_dict)
        rec = self._make_record(summary=summary)
        self._queue_process(rec)

    def send_run_sync(self, run_dict, timeout=None):
        run = self._make_run(run_dict)
        req = self._make_record(run=run)

        resp = self._request_response(req)
        return resp

    def send_stats(self, stats_dict):
        stats = self._make_stats(stats_dict)
        rec = self._make_record(stats=stats)
        self._queue_process(rec)

    def send_files(self, files_dict):
        files = self._make_files(files_dict)
        rec = self._make_record(files=files)
        self._queue_process(rec)

    def send_exit_code(self, exit_code):
        pass
