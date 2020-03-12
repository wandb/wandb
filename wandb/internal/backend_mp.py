import threading
import json
from six.moves import queue
import sys
import os
import logging
import six
import multiprocessing
import datetime

import wandb
from wandb.internal import wandb_internal_pb2
from wandb.internal import datastore

from wandb.apis import internal
from wandb.apis import file_stream

from wandb.stuff import io_wrap

import numpy as np
import platform

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


def wandb_read(fd):
    print("start reading", file=sys.stderr)
    while True:
        try:
            data = os.read(fd, 200)
        except OSError as e:
            print("problem", e, file=sys.stderr)
            return
        if len(data) == 0:
            break
        print("got data:", data, file=sys.stderr)
    print("done reading", file=sys.stderr)


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
    settings = {k: v for k, v in six.iteritems(settings) if k in ('project',) and v is not None}
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
                        settings['project'] = project_name
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
        elif t == "output":
            out = i.output
            #TODO: send this off
        else:
            print("what", t)
    if fs:
        fs.finish(0)


class WriteSerializingFile(object):
    """Wrapper for a file object that serializes writes.
    """

    def __init__(self, f):
        self.lock = threading.Lock()
        self.f = f

    def write(self, *args, **kargs):
        self.lock.acquire()
        try:
            self.f.write(*args, **kargs)
            self.f.flush()
        finally:
            self.lock.release()


def _get_stdout_stderr_streams():
        """Sets up STDOUT and STDERR streams. Only call this once."""
        if six.PY2 or not hasattr(sys.stdout, "buffer"):
            if hasattr(sys.stdout, "fileno") and sys.stdout.isatty():
                try:
                    stdout = os.fdopen(sys.stdout.fileno(), "w+", 0)
                    stderr = os.fdopen(sys.stderr.fileno(), "w+", 0)
                # OSError [Errno 22] Invalid argument wandb
                except OSError:
                    stdout = sys.stdout
                    stderr = sys.stderr
            else:
                stdout = sys.stdout
                stderr = sys.stderr
        else:  # we write binary so grab the raw I/O objects in python 3
            try:
                stdout = sys.stdout.buffer.raw
                stderr = sys.stderr.buffer.raw
            except AttributeError:
                # The testing environment and potentially others may have screwed with their
                # io so we fallback to raw stdout / err
                stdout = sys.stdout.buffer
                stderr = sys.stderr.buffer

        output_log_path = "output.txt"
        output_log = WriteSerializingFile(open(output_log_path, 'wb'))

        stdout_streams = [stdout, output_log]
        stderr_streams = [stderr, output_log]

#        if self._cloud:
#            # Tee stdout/stderr into our TextOutputStream, which will push lines to the cloud.
#            fs_api = self._api.get_file_stream_api()
#            self._stdout_stream = streaming_log.TextStreamPusher(
#                fs_api, util.OUTPUT_FNAME, prepend_timestamp=True)
#            self._stderr_stream = streaming_log.TextStreamPusher(
#                fs_api, util.OUTPUT_FNAME, line_prepend='ERROR',
#                prepend_timestamp=True)
#
#            stdout_streams.append(self._stdout_stream)
#            stderr_streams.append(self._stderr_stream)

        return stdout_streams, stderr_streams

def wandb_internal(settings, notify_queue, process_queue, req_queue, resp_queue, cancel_queue, child_pipe, log_fname, log_level, data_filename, use_redirect):
    #fd = multiprocessing.reduction.recv_handle(child_pipe)
    #if msvcrt:
    #    fd = msvcrt.open_osfhandle(fd, os.O_WRONLY)
    #os.write(fd, "this is a test".encode())
    #os.close(fd)

    if log_fname:
        setup_logging(log_fname, log_level)


    if use_redirect:
        pass
    else:
        if platform.system() == "Windows":
            #import msvcrt
            #stdout_handle = multiprocessing.reduction.recv_handle(child_pipe)
            #stderr_handle = multiprocessing.reduction.recv_handle(child_pipe)
            #stdout_fd = msvcrt.open_osfhandle(stdout_handle, os.O_RDONLY)
            #stderr_fd = msvcrt.open_osfhandle(stderr_handle, os.O_RDONLY)

            #logger.info("windows stdout: %d", stdout_fd)
            #logger.info("windows stderr: %d", stderr_fd)

            #read_thread = threading.Thread(name="wandb_read", target=wandb_read, args=(stdout_fd,))
            #read_thread.start()
            #stdout_read_file = os.fdopen(stdout_fd, 'rb')
            #stderr_read_file = os.fdopen(stderr_fd, 'rb')
            #stdout_streams, stderr_streams = _get_stdout_stderr_streams()
            #stdout_tee = io_wrap.Tee(stdout_read_file, *stdout_streams)
            #stderr_tee = io_wrap.Tee(stderr_read_file, *stderr_streams)
            pass
        else:
            stdout_fd = multiprocessing.reduction.recv_handle(child_pipe)
            stderr_fd = multiprocessing.reduction.recv_handle(child_pipe)
            logger.info("nonwindows stdout: %d", stdout_fd)
            logger.info("nonwindows stderr: %d", stderr_fd)

            #read_thread = threading.Thread(name="wandb_read", target=wandb_read, args=(stdout_fd,))
            #read_thread.start()
            stdout_read_file = os.fdopen(stdout_fd, 'rb')
            stderr_read_file = os.fdopen(stderr_fd, 'rb')
            stdout_streams, stderr_streams = _get_stdout_stderr_streams()
            stdout_tee = io_wrap.Tee(stdout_read_file, *stdout_streams)
            stderr_tee = io_wrap.Tee(stderr_read_file, *stderr_streams)

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
        #now = datetime.datetime.now()
        if name == "stdout":
            otype = wandb_internal_pb2.OutputData.OutputType.STDOUT
        elif name == "stderr":
            otype = wandb_internal_pb2.OutputData.OutputType.STDOUT
        else:
            # FIXME: throw error?
            print("unknown type")
        o = wandb_internal_pb2.OutputData(output_type=otype, str=data)
        o.timestamp.GetCurrentTime()
        rec = wandb_internal_pb2.Record()
        rec.output.CopyFrom(o)
        self.process_queue.put(rec)
        self.notify_queue.put(self.NOTIFY_PROCESS)

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

    def cleanup(self):
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True

        self.notify_queue.put(self.NOTIFY_SHUTDOWN)
        # TODO: make sure this is last in the queue?  lock?
        self.notify_queue.close()
        self.wandb_process.join()
        # No printing allowed from here until redirect restore!!!
