import threading
import json
import atexit
from six.moves import queue
import sys
import os
import logging
import six

import wandb
from wandb.internal import wandb_internal_pb2
from wandb.internal import datastore

from wandb.apis import internal
from wandb.apis import file_stream

import numpy as np

logger = logging.getLogger(__name__)


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


def setup_logging(log_fname, log_level, run_id=None):
    handler = logging.FileHandler(log_fname)
    handler.setLevel(log_level)

    class WBFilter(logging.Filter):
        def filter(self, record):
            record.run_id = run_id
            return True

    if run_id:
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d [%(run_id)s:%(filename)s:%(funcName)s():%(lineno)s] %(message)s')
    else:
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d [%(filename)s:%(funcName)s():%(lineno)s] %(message)s')

    handler.setFormatter(formatter)
    if run_id:
        handler.addFilter(WBFilter())
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)


def wandb_write(settings, q, stopped, data_filename):
    ds = datastore.DataStore()
    ds.open(data_filename)
    while not stopped.isSet():
        try:
            i = q.get(timeout=1)
        except queue.Empty:
            continue
        ds.write(i)
        #print("write", i)
    ds.close()


def wandb_send(settings, q, resp_q, stopped):
    fs = None
    run_id = None
    api = internal.Api(default_settings=settings)
    settings = {k: v for k, v in six.iteritems(settings) if k in ('project',)}
    while not stopped.isSet():
        try:
            i = q.get(timeout=1)
        except queue.Empty:
            continue
        #print("send", i)

        t = i.WhichOneof("data")
        if t is None:
            continue
        elif t == "run":
            run = i.run
            config = json.loads(run.config_json)
            ups = api.upsert_run(name=run.run_id, config=config, **settings)

            if i.control.req_resp:
                storage_id = ups.get("id")
                if storage_id:
                    i.run.storage_id = storage_id
                display_name = ups.get("displayName")
                if display_name:
                    i.run.name = display_name
                project = ups.get("project")
                if project:
                    project_name = project.get("name")
                    if project_name:
                        i.run.project = project_name
                    entity = project.get("entity")
                    if entity:
                        entity_name = entity.get("name")
                        if entity_name:
                            i.run.team = entity_name
                resp_q.put(i)

            #fs = file_stream.FileStreamApi(api, run.run_id, settings=settings)
            #fs.start()
            #self._fs['rfs'] = fs
            #self._fs['run_id'] = run.run_id
            fs = file_stream.FileStreamApi(api, run.run_id, settings=settings)
            fs.start()
            run_id = run.run_id
        elif t == "log":
            log = i.log
            d = json.loads(log.json)
            if fs:
                #print("about to send", d)
                x = fs.push("wandb-history.jsonl", json.dumps(d))
                #print("got", x)
        else:
            print("what", t)
    if fs:
        fs.finish(0)


def wandb_internal(settings, notify_queue, process_queue, req_queue, resp_queue, cancel_queue, child_pipe, log_fname, log_level, data_filename):
    #fd = multiprocessing.reduction.recv_handle(child_pipe)
    #if msvcrt:
    #    fd = msvcrt.open_osfhandle(fd, os.O_WRONLY)
    #os.write(fd, "this is a test".encode())
    #os.close(fd)

    if log_fname:
        setup_logging(log_fname, log_level)

    stopped = threading.Event()
   
    write_queue = queue.Queue()
    write_thread = threading.Thread(name="wandb_write", target=wandb_write, args=(settings, write_queue, stopped, data_filename))
    send_queue = queue.Queue()
    send_thread = threading.Thread(name="wandb_send", target=wandb_send, args=(settings, send_queue, resp_queue, stopped))

    write_thread.start()
    send_thread.start()
    
    done = False
    while not done:
        count = 0
        # TODO: think about this try/except clause
        try:
            while True:
                i = notify_queue.get()
                #print("got", i)
                if i == Backend.NOTIFY_PROCESS:
                    rec = process_queue.get()
                    send_queue.put(rec)
                    write_queue.put(rec)
                elif i == Backend.NOTIFY_SHUTDOWN:
                    # make sure queue is empty?
                    stopped.set()
                    done = True
                    break
                elif i == Backend.NOTIFY_REQUEST:
                    rec = req_queue.get()
                    # check if reqresp set
                    send_queue.put(rec)
                else:
                    print("unknown", i)
        except KeyboardInterrupt as e:
            print("\nInterrupt: {}\n".format(count))
            count += 1
        finally:
            if count >= 2:
                done = True
            if done:
                break


    write_thread.join()
    send_thread.join()


class Backend(object):
    NOTIFY_PROCESS = 1
    NOTIFY_SHUTDOWN = 2
    NOTIFY_REQUEST = 3

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

    def ensure_launched(self, settings=None, log_fname=None, log_level=None, data_fname=None):
        """Launch backend worker if not running."""
        log_fname = log_fname or ""
        log_level = log_level or logging.DEBUG
        settings = settings or {}
        settings = dict(settings)

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

        atexit.register(lambda: self._atexit_cleanup())

    def server_connect(self):
        """Connect to server."""
        pass

    def server_status(self):
        """Report server status."""
        pass

    def join(self):
        self._atexit_cleanup()

    def send_log(self, data):
        json_data = json.dumps(data, cls=WandBJSONEncoder)
        #json_data = json.dumps(data)
        l = wandb_internal_pb2.LogData(json=json_data)
        rec = wandb_internal_pb2.Record()
        rec.log.CopyFrom(l)
        self.process_queue.put(rec)
        self.notify_queue.put(self.NOTIFY_PROCESS)

    def _make_run(self, run_dict):
        run = wandb_internal_pb2.Run()
        run.run_id = run_dict['run_id']
        run.config_json = json.dumps(run_dict.get('config', {}))
        return run

    def _make_record(self, run=None):
        rec = wandb_internal_pb2.Record()
        if run:
            rec.run.CopyFrom(run)
        return rec

    def _queue_process(self, rec):
        self.process_queue.put(rec)
        self.notify_queue.put(self.NOTIFY_PROCESS)

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
        self.notify_queue.put(self.NOTIFY_REQUEST)

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

    def send_run_sync(self, run_dict, timeout=None):
        run = self._make_run(run_dict)
        req = self._make_record(run=run)

        resp = self._request_response(req)
        return resp

    def send_file_save(self, file_info):
        pass

    def send_exit_code(self, exit_code):
        pass

    def _atexit_cleanup(self):
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True

        self.notify_queue.put(self.NOTIFY_SHUTDOWN)
        # TODO: make sure this is last in the queue?  lock?
        self.notify_queue.close()
        self.wandb_process.join()
