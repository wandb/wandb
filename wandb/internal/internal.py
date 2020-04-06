# -*- coding: utf-8 -*-
"""
internal.
"""

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
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.interface import constants
from wandb.internal import datastore

from . import internal_api
from . import file_stream
from . import update

from .file_pusher import FilePusher

from wandb.stuff import io_wrap

from . import stats
from . import meta

import numpy as np  # type: ignore
import platform

logger = logging.getLogger(__name__)


class SettingsStatic(object):
    def __init__(self, config):
        object.__setattr__(self, "__dict__", dict(config))

    def __setattr__(self, name, value):
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def __setitem__(self, key, val):
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def keys(self):
        return self.__dict__.keys()

    def __getitem__(self, key):
        return self.__dict__[key]

    def __str__(self):
        return str(self.__dict__)


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


class _SendManager(object):
    def __init__(self, settings, q, resp_q):
        self._settings = settings
        self._q = q
        self._resp_q = resp_q

        self._fs = None
        self._pusher = None

        # is anyone using run_id?
        self._run_id = None

        self._entity = None
        self._project = None

        self._api = internal_api.Api(default_settings=settings)
        self._api_settings = dict()

        # TODO(jhr): do something better, why do we need to send full lines?
        self._partial_output = dict()

    def _flatten(self, dictionary):
        if type(dictionary) == dict:
            for k, v in list(dictionary.items()):
                if type(v) == dict:
                    self._flatten(v)
                    dictionary.pop(k)
                    for k2, v2 in v.items():
                        dictionary[k + "." + k2] = v2

    def handle_exit(self, data):
        # Ensure we've at least noticed every file in the run directory. Sometimes
        # we miss things because asynchronously watching filesystems isn't reliable.
        run_dir = self._settings.files_dir
        logger.info("scan: %s", run_dir)

        for dirpath, _, filenames in os.walk(run_dir):
            for fname in filenames:
                file_path = os.path.join(dirpath, fname)
                save_name = os.path.relpath(file_path, run_dir)
                logger.info("scan save: %s %s", file_path, save_name)
                self._save_file(save_name)

        if data.control.req_resp:
            self._resp_q.put(data)

    def handle_run(self, data):
        run = data.run
        run_tags = run.tags[:]
        config = json.loads(run.config_json)
        ups = self._api.upsert_run(
                entity=run.entity,
                project=run.project,
                group=run.group,
                job_type=run.job_type,
                name=run.run_id,
                display_name=run.name,
                notes=run.notes,
                tags=run_tags,
                config=config, 
                )

        if data.control.req_resp:
            storage_id = ups.get("id")
            if storage_id:
                data.run.storage_id = storage_id
            display_name = ups.get("displayName")
            if display_name:
                data.run.name = display_name
            project = ups.get("project")
            if project:
                project_name = project.get("name")
                if project_name:
                    data.run.project = project_name
                    self._project = project_name
                entity = project.get("entity")
                if entity:
                    entity_name = entity.get("name")
                    if entity_name:
                        data.run.entity = entity_name
                        self._entity = entity_name
            self._resp_q.put(data)

        if self._entity is not None:
            self._api_settings["entity"] = self._entity
        if self._project is not None:
            self._api_settings["project"] = self._project
        self._fs = file_stream.FileStreamApi(self._api, run.run_id, settings=self._api_settings)
        self._fs.start()
        self._pusher = FilePusher(self._api)
        self._run_id = run.run_id
        logger.info("run started: %s", self._run_id)

    def handle_log(self, data):
        log = data.log
        d = json.loads(log.json)
        if self._fs:
            #print("about to send", d)
            x = self._fs.push("wandb-history.jsonl", json.dumps(d))
            #print("got", x)

    def handle_summary(self, data):
        summary = data.summary
        d = json.loads(summary.summary_json)
        if self._fs:
            x = self._fs.push("wandb-summary.json", json.dumps(d))

    def handle_stats(self, data):
        stats = data.stats
        d = json.loads(stats.stats_json)
        if self._fs:
            row = dict(system=d)
            self._flatten(row)
            row["_wandb"] = True
            row["_timestamp"] = int(time.time())
            row['_runtime'] = int(time.time() - self._settings.start_time)
            x = self._fs.push("wandb-events.jsonl", json.dumps(row))

    def handle_output(self, data):
        out = data.output
        prepend = ""
        stream = "stdout"
        if out.output_type == wandb_internal_pb2.OutputData.OutputType.STDERR:
            stream = "stderr"
            prepend = "ERROR "
        line = out.str
        if not line.endswith("\n"):
            self._partial_output.setdefault(stream, "")
            self._partial_output[stream] += line
            # FIXME(jhr): how do we make sure this gets flushed? we might need this for other stuff like telemetry
        else:
            # TODO(jhr): use time from timestamp proto
            # FIXME(jhr): do we need to make sure we write full lines?  seems to be some issues with line breaks
            cur_time = time.time()
            timestamp = datetime.utcfromtimestamp(
                cur_time).isoformat() + ' '
            prev_str = self._partial_output.get(stream, "")
            line = u'{}{}{}{}'.format(prepend, timestamp, prev_str, line)
            self._fs.push("output.log", line)
            self._partial_output[stream] = ""

    def handle_config(self, data):
        cfg = data.config
        config = json.loads(cfg.config_json)
        ups = self._api.upsert_run(name=cfg.run_id, config=config, **self._api_settings)

    def _save_file(self, fname):
        directory = self._settings.files_dir
        logger.info("saving file %s at %s", fname, directory)
        path = os.path.abspath(os.path.join(directory, fname))
        logger.info("saving file %s at full %s", fname, path)
        self._pusher.update_file(fname, path)
        self._pusher.file_changed(fname, path)

    def handle_files(self, data):
        files = data.files
        for k in files.files:
            fname = k.name
            self._save_file(fname)

    def finish(self):
        if self._pusher:
            self._pusher.finish()
        if self._fs:
            # FIXME(jhr): now is a good time to output pending output lines
            self._fs.finish(0)
        if self._pusher:
            self._pusher.update_all_files()
            files = self._pusher.files()
            for f in files:
                logger.info("Finish Sync: %s", f)
            self._pusher.print_status()


def wandb_send(settings, q, resp_q, stopped):

    sh = _SendManager(settings, q, resp_q)

    while not stopped.isSet():
        try:
            i = q.get(timeout=1)
        except queue.Empty:
            continue

        t = i.WhichOneof("data")
        if t is None:
            continue
        handler = getattr(sh, 'handle_' + t, None)
        if handler is None:
            print("what", t)
            continue

        # run the handler
        handler(i)

    sh.finish()


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

    # Lets make sure we dont modify settings so use a static object
    settings = SettingsStatic(settings)

    run = None
    api = None

    pid = os.getpid()
    system_stats = stats.SystemStats(pid=pid, process_q=process_queue, notify_q=notify_queue)
    system_stats.start()

    run_meta = meta.Meta(settings=settings, process_q=process_queue, notify_q=notify_queue)
    run_meta.probe()
    run_meta.write()

    current_version = wandb.__version__
    update.check_available(current_version)

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

    system_stats.shutdown()

    write_thread.join()
    send_thread.join()
