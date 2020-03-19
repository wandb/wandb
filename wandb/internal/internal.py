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
from wandb.internal import datastore
from wandb.internal import constants

from wandb.apis import internal
from wandb.apis import file_stream

from wandb.stuff.file_pusher import FilePusher

from wandb.stuff import io_wrap

import numpy as np
import platform

logger = logging.getLogger(__name__)


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
    # print("start reading", file=sys.stderr)
    while True:
        try:
            data = os.read(fd, 200)
        except OSError as e:
            # print("problem", e, file=sys.stderr)
            return
        if len(data) == 0:
            break
        # print("got data:", data, file=sys.stderr)
    # print("done reading", file=sys.stderr)


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
    pusher = None
    run_id = None
    api = internal.Api(default_settings=settings)
    orig_settings = settings
    settings = {k: v for k, v in six.iteritems(settings) if k in ('project',) and v is not None}

    # TODO(jhr): do something better, why do we need to send full lines?
    partial_output = dict()

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
            pusher = FilePusher(api)
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
            prepend = ""
            stream = "stdout"
            if out.output_type == wandb_internal_pb2.OutputData.OutputType.STDERR:
                stream = "stderr"
                prepend = "ERROR "
            line = out.str
            if not line.endswith("\n"):
                partial_output.setdefault(stream, "")
                partial_output[stream] += line
                # FIXME(jhr): how do we make sure this gets flushed? we might need this for other stuff like telemetry
            else:
                # TODO(jhr): use time from timestamp proto
                # FIXME(jhr): do we need to make sure we write full lines?  seems to be some issues with line breaks
                cur_time = time.time()
                timestamp = datetime.utcfromtimestamp(
                    cur_time).isoformat() + ' '
                prev_str = partial_output.get(stream, "")
                line = u'{}{}{}{}'.format(prepend, timestamp, prev_str, line)
                fs.push("output.log", line)
                partial_output[stream] = ""
        elif t == "config":
            cfg = i.config
            config = json.loads(cfg.config_json)
            ups = api.upsert_run(name=cfg.run_id, config=config, **settings)
        elif t == "files":
            directory = orig_settings.get("files_dir")
            files = i.files
            for k in files.files:
                fname = k.name
                logger.info("saving file %s at %s", fname, directory)
                path = os.path.abspath(os.path.join(directory, fname))
                logger.info("saving file %s at full %s", fname, path)
                pusher.update_file(fname, path)
                pusher.file_changed(fname, path)
        else:
            print("what", t)
    if pusher:
        pusher.finish()
        pusher.print_status()
    if fs:
        # FIXME(jhr): now is a good time to output pending output lines
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
                if i == constants.NOTIFY_PROCESS:
                    rec = process_queue.get()
                    send_queue.put(rec)
                    write_queue.put(rec)
                elif i == constants.NOTIFY_SHUTDOWN:
                    # make sure queue is empty?
                    stopped.set()
                    done = True
                    break
                elif i == constants.NOTIFY_REQUEST:
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
