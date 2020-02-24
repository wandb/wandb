import threading
import json
import atexit
import queue
import sys
import os
import logging


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


def wandb_write(q, stopped):
    ds = datastore.DataStore()
    ds.open("out.dat")
    while not stopped.isSet():
        try:
            i = q.get(timeout=1)
        except queue.Empty:
            continue
        ds.write(i)
        #print("write", i)
    ds.close()


def wandb_send(q, stopped):
    fs = None
    run_id = None
    api = internal.Api()
    #settings=dict(entity="jeff", project="uncategorized")
    settings=dict(project="uncategorized")
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
            r = api.upsert_run(name=run.run_id, config=config, **settings)
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


def wandb_internal(notify_queue, process_queue, child_pipe, log_fname, log_level):
    #fd = multiprocessing.reduction.recv_handle(child_pipe)
    #if msvcrt:
    #    fd = msvcrt.open_osfhandle(fd, os.O_WRONLY)
    #os.write(fd, "this is a test".encode())
    #os.close(fd)

    if log_fname:
        setup_logging(log_fname, log_level)

    stopped = threading.Event()
   
    write_queue = queue.Queue()
    write_thread = threading.Thread(name="wandb_write", target=wandb_write, args=(write_queue, stopped))
    send_queue = queue.Queue()
    send_thread = threading.Thread(name="wandb_send", target=wandb_send, args=(send_queue, stopped))

    write_thread.start()
    send_thread.start()
    
    done = False
    while not done:
        count = 0
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

    def __init__(self, mode=None):
        self.wandb_process = None
        self.fd_pipe_parent = None
        self.process_queue = None
        self.async_queue = None
        self.fd_request_queue = None
        self.fd_response_queue = None
        self.request_queue = None
        self.response_queue = None
        self.notify_queue = None  # notify activity on ...

        self._done = False
        self._wl = wandb.setup()

    def ensure_launched(self, log_fname=None, log_level=None):
        """Launch backend worker if not running."""
        log_fname = log_fname or ""
        log_level = log_level or logging.DEBUG

        fd_pipe_child, fd_pipe_parent = self._wl._multiprocessing.Pipe()
        process_queue = self._wl._multiprocessing.Queue()
        async_queue = self._wl._multiprocessing.Queue()
        fd_request_queue = self._wl._multiprocessing.Queue()
        fd_response_queue = self._wl._multiprocessing.Queue()
        request_queue = self._wl._multiprocessing.Queue()
        response_queue = self._wl._multiprocessing.Queue()
        notify_queue = self._wl._multiprocessing.Queue()

        wandb_process = self._wl._multiprocessing.Process(target=wandb_internal,
                args=(
                    notify_queue,
                    process_queue,
                    fd_pipe_child,
                    log_fname,
                    log_level,
                    ))
        wandb_process.name = "wandb_internal"

        # Support running code without a: __name__ == "__main__"
        save_mod_name = None
        save_mod_path = None
        main_module = sys.modules['__main__']
        main_mod_name = getattr(main_module.__spec__, "name", None)
        main_mod_path = getattr(main_module, '__file__', None)
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

        self.wandb_process = wandb_process
        self.fd_pipe_parent = fd_pipe_parent
        self.process_queue = process_queue
        self.async_queue = async_queue
        self.fd_request_queue = fd_request_queue
        self.fd_response_queue = fd_response_queue
        self.request_queue = request_queue
        self.response_queue = response_queue
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

    def log(self, data):
        json_data = json.dumps(data, cls=WandBJSONEncoder)
        #json_data = json.dumps(data)
        l = wandb_internal_pb2.LogData(json=json_data)
        rec = wandb_internal_pb2.Record()
        rec.log.CopyFrom(l)
        self.process_queue.put(rec)
        self.notify_queue.put(self.NOTIFY_PROCESS)

    def run_update(self, run_dict):
        run = wandb_internal_pb2.Run()
        run.run_id = run_dict['run_id']
        run.config_json = json.dumps(run_dict.get('config', {}))
        rec = wandb_internal_pb2.Record()
        rec.run.CopyFrom(run)
        self.process_queue.put(rec)
        self.notify_queue.put(self.NOTIFY_PROCESS)

    def _atexit_cleanup(self):
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True

        self.notify_queue.put(self.NOTIFY_SHUTDOWN)
        # TODO: make sure this is last in the queue?  lock?
        self.notify_queue.close()
        self.wandb_process.join()
