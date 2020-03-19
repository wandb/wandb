import threading
import json
from six.moves import queue
import sys
import os
import logging
import six
import multiprocessing
from datetime import date, datetime
import time

import wandb

from wandb.internal import wandb_internal_pb2
from wandb.internal.internal import wandb_internal
from wandb.internal import constants

import numpy as np
import platform

logger = logging.getLogger("wandb")


def is_numpy_array(obj):
    return np and isinstance(obj, np.ndarray)


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

    #if is_tf_eager_tensor_typename(typename):
    #    obj = obj.numpy()
    #elif is_tf_tensor_typename(typename):
    #    obj = obj.eval()
    #elif is_pytorch_tensor_typename(typename):
    #    try:
    #        if obj.requires_grad:
    #            obj = obj.detach()
    #    except AttributeError:
    #        pass  # before 0.4 is only present on variables
#
#        try:
#            obj = obj.data
#        except RuntimeError:
#            pass  # happens for Tensors before 0.4
#
#        if obj.size():
#            obj = obj.numpy()
#        else:
#            return obj.item(), True

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
        tmp_obj, converted = json_friendly(obj)
        if converted:
            return tmp_obj
        return json.JSONEncoder.default(self, obj)


class Backend(object):

    class ExceptionTimeout(Exception):
        pass

    def __init__(self, mode=None):
        self.wandb_process = None
        self.fd_pipe_parent = None
        self.process_queue = None
        # self.fd_request_queue = None
        # self.fd_response_queue = None
        self.req_queue = None
        self.resp_queue = None
        self.cancel_queue = None
        self.notify_queue = None  # notify activity on ...

        self._done = False
        self._wl = wandb.setup()

    def ensure_launched(self, settings=None, log_fname=None, log_level=None, data_fname=None, stdout_fd=None, stderr_fd=None, use_redirect=None):
        """Launch backend worker if not running."""
        log_fname = log_fname or ""
        log_level = log_level or logging.DEBUG
        settings = settings or {}
        settings = dict(settings)

        #os.set_inheritable(stdout_fd, True)
        #os.set_inheritable(stderr_fd, True)
        #stdout_read_file = os.fdopen(stdout_fd, 'rb')
        #stderr_read_file = os.fdopen(stderr_fd, 'rb')

        fd_pipe_child, fd_pipe_parent = self._wl._multiprocessing.Pipe()

        process_queue = self._wl._multiprocessing.Queue()
        # async_queue = self._wl._multiprocessing.Queue()
        # fd_request_queue = self._wl._multiprocessing.Queue()
        # fd_response_queue = self._wl._multiprocessing.Queue()
        # TODO: should this be one item just to make sure it stays fully synchronous?
        req_queue = self._wl._multiprocessing.Queue()
        resp_queue = self._wl._multiprocessing.Queue()
        cancel_queue = self._wl._multiprocessing.Queue()
        notify_queue = self._wl._multiprocessing.Queue()

        wandb_process = self._wl._multiprocessing.Process(target=wandb_internal,
                args=(
                    settings,
                    notify_queue,
                    process_queue,
                    req_queue,
                    resp_queue,
                    cancel_queue,
                    fd_pipe_child,
                    log_fname,
                    log_level,
                    data_fname,
                    use_redirect,
                    ))
        wandb_process.name = "wandb_internal"

        # Support running code without a: __name__ == "__main__"
        save_mod_name = None
        save_mod_path = None
        main_module = sys.modules['__main__']
        main_mod_spec = getattr(main_module, "__spec__", None)
        main_mod_path = getattr(main_module, '__file__', None)
        main_mod_name = None
        if main_mod_spec:
            main_mod_name = getattr(main_mod_spec, "name", None)
        if main_mod_name is not None:
            save_mod_name = main_mod_name
            main_module.__spec__.name = "wandb.internal.mpmain"
        elif main_mod_path is not None:
            save_mod_path = main_module.__file__
            fname = os.path.join(os.path.dirname(wandb.__file__), "internal", "mpmain", "__main__.py")
            main_module.__file__ = fname

        # Start the process with __name__ == "__main__" workarounds
        wandb_process.start()

        if use_redirect:
            pass
        else:
            if platform.system() == "Windows":
                # https://bugs.python.org/issue38188
                #import msvcrt
                #print("DEBUG1: {}".format(stdout_fd))
                #stdout_fd = msvcrt.get_osfhandle(stdout_fd)
                #print("DEBUG2: {}".format(stdout_fd))
                # stderr_fd = msvcrt.get_osfhandle(stderr_fd)
                #multiprocessing.reduction.send_handle(fd_pipe_parent, stdout_fd,  wandb_process.pid)
                # multiprocessing.reduction.send_handle(fd_pipe_parent, stderr_fd,  wandb_process.pid)

                # should we do this?
                #os.close(stdout_fd)
                #os.close(stderr_fd)
                pass
            else:
                multiprocessing.reduction.send_handle(fd_pipe_parent, stdout_fd,  wandb_process.pid)
                multiprocessing.reduction.send_handle(fd_pipe_parent, stderr_fd,  wandb_process.pid)

                # should we do this?
                os.close(stdout_fd)
                os.close(stderr_fd)

        # Undo temporary changes from: __name__ == "__main__"
        if save_mod_name:
            main_module.__spec__.name = save_mod_name
        elif save_mod_path:
            main_module.__file__ = save_mod_path

        self.fd_pipe_parent = fd_pipe_parent

        self.wandb_process = wandb_process

        self.process_queue = process_queue
        # self.async_queue = async_queue
        # self.fd_request_queue = fd_request_queue
        # self.fd_response_queue = fd_response_queue
        self.req_queue = req_queue
        self.resp_queue = resp_queue
        self.cancel_queue = cancel_queue
        self.notify_queue = notify_queue

    def server_connect(self):
        """Connect to server."""
        pass

    def server_status(self):
        """Report server status."""
        pass

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

    def _make_files(self, files_dict):
        files = wandb_internal_pb2.FilesData()
        for path in files_dict['files']:
            f = files.files.add()
            f.name = path
        return files

    def _make_record(self, run=None, config=None, files=None):
        rec = wandb_internal_pb2.Record()
        if run:
            rec.run.CopyFrom(run)
        if config:
            rec.config.CopyFrom(config)
        if files:
            rec.files.CopyFrom(files)
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
        self.req_queue.put(rec)
        self.notify_queue.put(constants.NOTIFY_REQUEST)

        try:
            rsp = self.resp_queue.get(timeout=timeout)
        except queue.Empty:
            self._request_flush()
            raise Backend.ExceptionTimeout("timeout")

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

    def send_run_sync(self, run_dict, timeout=None):
        run = self._make_run(run_dict)
        req = self._make_record(run=run)

        resp = self._request_response(req)
        return resp

    def send_files(self, files_dict):
        files = self._make_files(files_dict)
        rec = self._make_record(files=files)
        self._queue_process(rec)

    def send_exit_code(self, exit_code):
        pass

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
