# -*- encoding: utf-8 -*-

import errno
import json
import logging
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import time
from tempfile import NamedTemporaryFile
import threading
import yaml
import numbers
import inspect
import glob
import platform
import fnmatch

import click
from pkg_resources import parse_version
import six
from six.moves import queue
import requests
from watchdog.observers.polling import PollingObserver
from watchdog.events import PatternMatchingEventHandler
import webbrowser

import wandb
from wandb.apis import file_stream
from wandb import __version__
from wandb import env as wandb_env
from wandb import Error
from wandb import io_wrap
from wandb import jsonlfile
from wandb import file_pusher
from wandb import meta
from wandb.core import START_TIME
from wandb import sparkline
from wandb import stats
from wandb import streaming_log
from wandb import util
from wandb import wandb_config as config
from wandb import wandb_run
from wandb import wandb_socket
from wandb.compat import windows
from wandb.apis import InternalApi
from wandb.apis import CommError


logger = logging.getLogger(__name__)


class LaunchError(Error):
    """Raised when there's an error starting up."""


class FileTailer(object):
    def __init__(self, path, on_read_fn, binary=False, seek_end=False):
        self._path = path
        mode = 'r'
        if binary:
            mode = 'rb'
        self._file = open(path, mode)
        if seek_end:
            self._file.seek(0, 2)  # seek to 0 bytes from end (2 means end)
        self._on_read_fn = on_read_fn
        self.running = True
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.start()

    def _thread_body(self):
        while self.running:
            where = self._file.tell()
            data = self._file.read(1024)
            if not data:
                time.sleep(1)
                # required for to get python2 working (Issue #50)
                self._file.seek(where)
            else:
                self._on_read_fn(data)
        data = self._file.read()
        if data:
            self._on_read_fn(data)

    def stop(self):
        self.running = False
        self._thread.join()
        self._file.close()


class FileEventHandler(object):
    def __init__(self, file_path, save_name, api, *args, **kwargs):
        self.file_path = file_path
        # Convert windows paths to unix paths 
        save_name = util.to_forward_slash_path(save_name)
        self.save_name = save_name
        self._api = api

    def on_created(self):
        pass

    def on_modified(self):
        pass

    def on_renamed(self, new_path, new_name):
        self.file_path = new_path
        self.save_name = new_name

    def finish(self):
        pass


class FileEventHandlerOverwrite(FileEventHandler):
    def __init__(self, file_path, save_name, api, file_pusher, *args, **kwargs):
        super(FileEventHandlerOverwrite, self).__init__(
            file_path, save_name, api, *args, **kwargs)
        self._file_pusher = file_pusher

    def on_created(self):
        self.on_modified()

    def on_modified(self):
        self._file_pusher.file_changed(self.save_name, self.file_path)


class FileEventHandlerOverwriteOnce(FileEventHandler):
    """This file handler is meant for files like metadata which may update during the run but should be uploaded upon creation"""
    def __init__(self, file_path, save_name, api, file_pusher, *args, **kwargs):
        super(FileEventHandlerOverwriteOnce, self).__init__(
            file_path, save_name, api, *args, **kwargs)
        self._file_pusher = file_pusher

    def on_created(self):
        self._file_pusher.file_changed(self.save_name, self.file_path)

    def finish(self):
        self._file_pusher.file_changed(self.save_name, self.file_path)

class FileEventHandlerThrottledOverwrite(FileEventHandler):
    """This file handler uploads the file atmost every 15 seconds and only if it's size has increased by 20%"""
    # Don't upload
    RATE_LIMIT_SECONDS = 15

    # Wait to upload until size has increased 20% from last upload
    RATE_LIMIT_SIZE_INCREASE = 1.2

    def __init__(self, file_path, save_name, api, file_pusher, *args, **kwargs):
        super(FileEventHandlerThrottledOverwrite, self).__init__(
            file_path, save_name, api, *args, **kwargs)
        self._file_pusher = file_pusher
        self._last_uploaded_time = None
        self._last_uploaded_size = 0

    def on_created(self):
        self.on_modified()

    @property
    def current_size(self):
        return os.path.getsize(self.file_path)

    def on_modified(self):
        # Don't upload anything if it's zero size.
        if self.current_size == 0:
            return 0

        if self._last_uploaded_time:
            # Check rate limit by time elapsed
            time_elapsed = time.time() - self._last_uploaded_time
            if time_elapsed < self.RATE_LIMIT_SECONDS:
                return time_elapsed
            # Check rate limit by size increase
            size_increase = self.current_size / float(self._last_uploaded_size)
            if size_increase < self.RATE_LIMIT_SIZE_INCREASE:
                return time_elapsed

        self.save_file()
        return 0

    def finish(self):
        self._file_pusher.file_changed(self.save_name, self.file_path)

    def save_file(self):
        self._last_uploaded_time = time.time()
        self._last_uploaded_size = self.current_size
        self._file_pusher.file_changed(self.save_name, self.file_path)


class FileEventHandlerThrottledOverwriteMinWait(FileEventHandlerThrottledOverwrite):
    """This event handler will upload files every N seconds as it changes throttling as the size increases"""
    TEN_MB =     10000000
    HUNDRED_MB = 100000000
    ONE_GB =     1000000000

    def min_wait_for_size(self, size):
        if self.current_size < self.TEN_MB:
            return 60
        elif self.current_size < self.HUNDRED_MB:
            return 5 * 60
        elif self.current_size < self.ONE_GB:
            return 10 * 60
        else:
            return 20 * 60

    def on_modified(self):
        time_elapsed = super(FileEventHandlerThrottledOverwriteMinWait, self).on_modified()
        # Check max elapsed time
        if time_elapsed > self.min_wait_for_size(self.current_size):
            self.save_file()

class FileEventHandlerOverwriteDeferred(FileEventHandler):
    """This file handler only updates at the end of the run"""
    def __init__(self, file_path, save_name, api, file_pusher, *args, **kwargs):
        super(FileEventHandlerOverwriteDeferred, self).__init__(
            file_path, save_name, api, *args, **kwargs)
        self._file_pusher = file_pusher

    def finish(self):
        # We use copy=False to avoid possibly expensive copies, and because
        # user files shouldn't still be changing at the end of the run.
        self._file_pusher.file_changed(self.save_name, self.file_path, copy=False)


class FileEventHandlerConfig(FileEventHandler):
    """Set the config instead of uploading the file"""
    RATE_LIMIT_SECONDS = 30

    def __init__(self, file_path, save_name, api, file_pusher, run, *args, **kwargs):
        self._api = api
        super(FileEventHandlerConfig, self).__init__(
            file_path, save_name, api, *args, **kwargs)
        self._last_sent = time.time() - self.RATE_LIMIT_SECONDS
        self._file_pusher = file_pusher
        self._run = run
        self._thread = None

    def on_created(self):
        self._eventually_update()

    def on_modified(self):
        self._eventually_update()

    def _eventually_update(self):
        if self._thread:
            # assume the existing thread will catch this update
            return

        if time.time() - self._last_sent >= self.RATE_LIMIT_SECONDS:
            self._update()
        else:
            self._thread = threading.Timer(
                self.RATE_LIMIT_SECONDS, self._thread_update)
            self._thread.start()

    def _thread_update(self):
        try:
            self._update()
        finally:
            self._thread = None

    def _update(self):
        try:
            with open(self.file_path) as f:
                config_dict = util.load_yaml(f)
        except yaml.parser.ParserError:
            wandb.termlog(
                "Unable to parse config file; probably being modified by user process?")
            return

        # TODO(adrian): ensure the file content will exactly match Bucket.config
        # ie. push the file content as a string
        self._api.upsert_run(id=self._run.storage_id, config=config_dict)
        self._file_pusher.file_changed(self.save_name, self.file_path)
        self._last_sent = time.time()

    def finish(self):
        if self._thread:
            # Cancel the current thread to keep moving
            self._thread.cancel()
            self._thread = None

        self._update()


class FileEventHandlerSummary(FileEventHandler):
    """Read the file and add to the file push api"""

    def __init__(self, file_path, save_name, api, file_pusher, run, *args, **kwargs):
        super(FileEventHandlerSummary, self).__init__(
            file_path, save_name, api, *args, **kwargs)
        self._api = api
        self._file_pusher = file_pusher

    def on_created(self):
        self.on_modified()

    def on_modified(self):
        with open(self.file_path) as f:
            self._api.get_file_stream_api().push(self.save_name, f.read())

    def finish(self):
        with open(self.file_path) as f:
            self._api.get_file_stream_api().push(self.save_name, f.read())
        self._file_pusher.file_changed(self.save_name, self.file_path)


class FileEventHandlerTextStream(FileEventHandler):
    def __init__(self, *args, **kwargs):
        self._seek_end = kwargs.pop('seek_end', None)
        super(FileEventHandlerTextStream, self).__init__(*args, **kwargs)
        self._tailer = None
        if self._seek_end:
            # We need to call _setup up in the case of resumed runs
            # because we will start logging immediatly, so on_modified
            # would seek the FileTailer to after the most recent log
            self._setup()

    def on_created(self):
        if self._tailer:
            logger.error(
                'Streaming file created twice in same run: %s', self.file_path)
            return
        self._setup()

    def on_modified(self):
        if self._tailer:
            return
        self._setup()

    def _setup(self):
        fsapi = self._api.get_file_stream_api()
        pusher = streaming_log.TextStreamPusher(fsapi, self.save_name)

        def on_read(data):
            pusher.write_string(data)

        self._tailer = FileTailer(
            self.file_path, on_read, seek_end=self._seek_end)

    def finish(self):
        if self._tailer:
            self._tailer.stop()
            self._tailer = None

class FileEventHandlerBinaryStream(FileEventHandler):
    def __init__(self, *args, **kwargs):
        super(FileEventHandlerBinaryStream, self).__init__(*args, **kwargs)
        self._tailer = None

    def on_created(self):
        if self._tailer:
            logger.error(
                'Streaming file created twice in same run: %s', self.file_path)
            return
        self._setup()

    def on_modified(self):
        if self._tailer:
            return
        self._setup()

    def _setup(self):
        fsapi = self._api.get_file_stream_api()

        def on_read(data):
            fsapi.push(self.save_name, data)

        self._tailer = FileTailer(self.file_path, on_read, binary=True)


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


class Process(object):
    """Represents a running process with an interface that
    mimics Popen's.

    Only works on Unix-y systems.

    TODO(adrian): probably rewrite using psutil.Process
    """

    def __init__(self, pid):
        self.returncode = None
        self.pid = pid

    def poll(self):
        if self.returncode is None:
            try:
                if platform.system() == "Windows":
                    if windows.pid_running(self.pid) == False:
                        raise OSError(0, "Process isn't running")
                else:
                    os.kill(self.pid, 0)
            except OSError as err:
                if err.errno == errno.ESRCH:
                    # ESRCH == No such process
                    # we have no way of getting the real return code, so just set it to 0
                    self.returncode = 0
                elif err.errno == errno.EPERM:
                    # EPERM clearly means there's a process to deny access to
                    pass
                else:
                    # According to "man 2 kill" possible error values are
                    # (EINVAL, EPERM, ESRCH)
                    raise

        return self.returncode

    def wait(self):
        while self.poll() is None:
            time.sleep(1)

    def interrupt(self):
        os.kill(self.pid, signal.SIGINT)

    def terminate(self):
        os.kill(self.pid, signal.SIGTERM)

    def kill(self):
        os.kill(self.pid, signal.SIGKILL)

def format_run_name(run):
    "Simple helper to not show display name if its the same as id"
    return " "+run.name+":" if run.name and run.name != run.id else ":"

class RunStatusChecker(object):
    """Polls the backend periodically to check on this run's status.

    For now, we just use this to figure out if the user has requested a stop.
    TODO(adrnswanberg): Use this as more of a general heartbeat check.
    """

    def __init__(self, run, api, stop_requested_handler, polling_interval=15):
        self._run = run
        self._api = api
        self._polling_interval = polling_interval
        self._stop_requested_handler = stop_requested_handler

        self._shutdown_event = threading.Event()
        self._thread = threading.Thread(target=self.check_status)
        self._thread.start()

    def check_status(self):
        shutdown_requested = False
        while not shutdown_requested:
            try:
                should_exit = self._api.check_stop_requested(
                    project_name=self._run.project_name(),
                    entity_name=self._run.entity,
                    run_id=self._run.id)
            except CommError as e:
                logger.exception("Failed to check stop requested status: %s" % e.exc)
                should_exit = False
            except:
                logger.exception("An unknown error occurred while checking stop requested status. Continuing anyway..")
                should_exit = False

            if should_exit:
                self._stop_requested_handler()
                return
            else:
                shutdown_requested = self._shutdown_event.wait(self._polling_interval)

    def shutdown(self):
        self._shutdown_event.set()
        self._thread.join()


class RunManager(object):
    """Manages a run's process, wraps its I/O, and synchronizes its files.
    """
    CRASH_NOSYNC_TIME = 30

    def __init__(self, run, project=None, tags=[], cloud=True, output=True, port=None):
        self._run = run
        self._tags = tags
        self._cloud = cloud
        self._output = output
        self._port = port

        # Connect to the server early to let it know we are starting up
        self._socket = wandb_socket.Client(self._port)

        self._api = run.api
        self._project = self._resolve_project_name(project)

        self._config = run.config

        self._file_count = 0
        self._init_file_observer()

        # Calling .start() on _meta and _system_stats will spin a thread that reports system stats every 30 seconds
        self._system_stats = stats.SystemStats(run, self._api)
        self._meta = meta.Meta(self._api, self._run.dir)
        self._meta.data["jobType"] = self._run.job_type
        self._meta.data["mode"] = self._run.mode
        if self._run.name:
            self._meta.data["name"] = self._run.name
        if self._run.notes:
            self._meta.data["notes"] = self._run.notes
        if self._project:
            self._meta.data["project"] = self._project
        if self._run.program:
            self._meta.data["program"] = self._run.program
            self._meta.data["args"] = self._run.args
        # Set code path in config
        if self._meta.data.get("codePath"):
            self._config._set_wandb("code_path", util.to_forward_slash_path(
                os.path.join("code", self._meta.data["codePath"])))
            self._config.persist()
        # Write our initial metadata after overriding the defaults
        self._meta.write()
        self._tensorboard_watchers = []
        self._tensorboard_consumer = None
        self._tensorboard_lock = threading.Lock()
        self._watcher_queue = queue.PriorityQueue()

        # We'll conditionally create one of these when running in headless mode.
        self._run_status_checker = None

        # This allows users to specify files they want uploaded during the run
        self._user_file_policies = {
            "end": [],
            "live": []
        }
        self._file_policy_lock = threading.Lock()

        logger.debug("Initialized sync for %s/%s", self._project, self._run.id)

    def _resolve_project_name(self, project_name=None):
        if project_name is not None:
            return project_name

        project_name = self._api.settings('project')
        if project_name is not None:
            return project_name

        project_name = self._run.auto_project_name(self._api)
        if project_name is not None:
            return project_name


    """ FILE SYNCING / UPLOADING STUFF """

    def _init_file_observer(self):
        self._file_pusher = file_pusher.FilePusher(self._api)
        # FileEventHandlers (any of the classes at the top) indexed by "save_name," which is the file's path relative to the run directory
        self._file_event_handlers = {}

        # We use the polling observer because inotify was flaky and could require changes to sysctl.conf
        self._file_observer = PollingObserver()
        self._file_observer.schedule(self._per_file_event_handler(), self._run.dir, recursive=True)

        # We lock this when the back end is down so Watchdog will keep track of all
        # the file events that happen. Then, when the back end comes back up, we unlock
        # it so all the outstanding events will get handled properly. Watchdog's queue
        # only keeps at most one event per file.
        self._file_observer_lock = threading.Lock()
        # It starts acquired. We release it when we want to allow the events to happen.
        # (ie. after the Run is successfully created)
        self._block_file_observer()

        # Start watching for file changes right away so we can be sure we don't miss anything.
        # We don't have to worry about handlers actually being called because of the lock.
        self._file_observer.start()

    @property
    def emitter(self):
        try:
            return next(iter(self._file_observer.emitters))
        except StopIteration:
            return None

    @property
    def run(self):
        return self._run

    def _per_file_event_handler(self):
        """Create a Watchdog file event handler that does different things for every file
        """
        file_event_handler = PatternMatchingEventHandler()
        file_event_handler.on_created = self._on_file_created
        file_event_handler.on_modified = self._on_file_modified
        file_event_handler.on_moved = self._on_file_moved
        file_event_handler._patterns = [
            os.path.join(self._run.dir, os.path.normpath('*'))]
        # Ignore hidden files/folders
        file_event_handler._ignore_patterns = [
            '*.tmp',
            os.path.join(self._run.dir, ".*"),
            os.path.join(self._run.dir, "*/.*"),
        ]
        for glob in self._api.settings("ignore_globs"):
            file_event_handler._ignore_patterns.append(
                os.path.join(self._run.dir, glob))

        return file_event_handler

    def _block_file_observer(self):
        self._file_observer_lock.acquire()

    def _unblock_file_observer(self):
        self._file_observer_lock.release()

    def _ensure_file_observer_is_unblocked(self):
        self._block_file_observer()
        self._unblock_file_observer()

    def _end_file_syncing(self, exitcode):
        try:
            # avoid hanging if we crashed before the observer was started
            if self._file_observer.is_alive():
                # rather unfortunatly we need to manually do a final scan of the dir
                # with `queue_events`, then iterate through all events before stopping
                # the observer to catch all files written.  First we need to prevent the
                # existing thread from consuming our final events, then we process each one.
                self._file_observer._timeout = 0
                self._file_observer._stopped_event.set()
                self._file_observer.join()
                self.emitter.queue_events(0)
                while True:
                    try:
                        self._file_observer.dispatch_events(self._file_observer.event_queue, 0)
                    except queue.Empty:
                        break
                # Calling stop unschedules any inflight events so we manually handled them above 
                self._file_observer.stop()
        # TODO: py2 TypeError: PyCObject_AsVoidPtr called with null pointer
        except TypeError:
            pass
        # TODO: py3 SystemError: <built-in function stop> returned a result with an error set
        except SystemError:
            pass

        # Ensure we've at least noticed every file in the run directory. Sometimes
        # we miss things because asynchronously watching filesystems isn't reliable.
        ignore_globs = self._api.settings("ignore_globs")
        for dirpath, _, filenames in os.walk(self._run.dir):
            for fname in filenames:
                file_path = os.path.join(dirpath, fname)
                save_name = os.path.relpath(file_path, self._run.dir)
                if any([fnmatch.fnmatch(save_name, glob) for glob in ignore_globs]):
                    continue
                if save_name not in self._file_event_handlers:
                    self._get_file_event_handler(file_path, save_name).on_created()

        """Stops file syncing/streaming but doesn't actually wait for everything to
        finish. We print progress info later.
        """
        # TODO: there was a case where _file_event_handlers was getting modified in the loop.
        for handler in list(self._file_event_handlers.values()):
            handler.finish()
        self._file_pusher.finish()
        self._api.get_file_stream_api().finish(exitcode)
        # In Jupyter notebooks, wandb.init can be called multiple times in the same
        # process, creating new runs each time. This ensures we get a new file stream
        # thread
        self._api._file_stream_api = None

    # TODO: limit / throttle the number of adds / pushes
    def _on_file_created(self, event):
        logger.info('file/dir created: %s', event.src_path)
        if os.path.isdir(event.src_path):
            return None
        self._file_count += 1
        if self._file_count % 100 == 0:
            self.emitter._timeout = int(self._file_count / 100) + 1
        save_name = os.path.relpath(event.src_path, self._run.dir)
        self._ensure_file_observer_is_unblocked()
        self._get_file_event_handler(event.src_path, save_name).on_created()

    def _on_file_modified(self, event):
        logger.info('file/dir modified: %s', event.src_path)
        if os.path.isdir(event.src_path):
            return None
        save_name = os.path.relpath(event.src_path, self._run.dir)
        self._ensure_file_observer_is_unblocked()
        self._get_file_event_handler(event.src_path, save_name).on_modified()

    def _on_file_moved(self, event):
        logger.info('file/dir moved: %s -> %s',
                    event.src_path, event.dest_path)
        if os.path.isdir(event.dest_path):
            return None
        old_save_name = os.path.relpath(event.src_path, self._run.dir)
        new_save_name = os.path.relpath(event.dest_path, self._run.dir)
        self._ensure_file_observer_is_unblocked()

        # We have to move the existing file handler to the new name, and update the stats
        handler = self._get_file_event_handler(event.src_path, old_save_name)
        self._file_event_handlers[new_save_name] = handler
        del self._file_event_handlers[old_save_name]
        self._file_pusher.rename_file(old_save_name, new_save_name, event.dest_path)

        handler.on_renamed(event.dest_path, new_save_name)

    def _get_file_event_handler(self, file_path, save_name):
        """Get or create an event handler for a particular file.

        file_path: the file's actual path
        save_name: its path relative to the run directory (aka the watch directory)
        """
        self._file_pusher.update_file(save_name, file_path)  # track upload progress

        if save_name not in self._file_event_handlers:
            if save_name == 'wandb-history.jsonl':
                self._api.get_file_stream_api().set_file_policy(save_name, file_stream.JsonlFilePolicy())
                self._file_event_handlers['wandb-history.jsonl'] = FileEventHandlerTextStream(
                    file_path, 'wandb-history.jsonl', self._api)
            elif save_name == 'wandb-events.jsonl':
                self._api.get_file_stream_api().set_file_policy(save_name, file_stream.JsonlFilePolicy())
                self._file_event_handlers['wandb-events.jsonl'] = FileEventHandlerTextStream(
                    file_path, 'wandb-events.jsonl', self._api)
            elif 'tfevents' in save_name or 'graph.pbtxt' in save_name:
                # overwrite the tensorboard but not every reload -- just
                # frequently enough to resemble realtime
                self._file_event_handlers[save_name] = FileEventHandlerThrottledOverwrite(
                    file_path, save_name, self._api, self._file_pusher)
            # Don't try to stream tensorboard files for now.
            # elif 'tfevents' in save_name:
            #    # TODO: This is hard-coded, but we want to give users control
            #    # over streaming files (or detect them).
            #    self._api.get_file_stream_api().set_file_policy(save_name,
            #                                                    file_stream.BinaryFilePolicy())
            #    self._file_event_handlers[save_name] = FileEventHandlerBinaryStream(
            #        file_path, save_name, self._api)
            # Overwrite handler (non-deferred) has a bug, wherein if the file is truncated
            # during upload, the request to Google hangs (at least, this is my working
            # theory). So for now we defer uploading everything til the end of the run.
            # TODO: send wandb-summary during run. One option is to copy to a temporary
            # file before uploading.
            elif save_name == config.FNAME:
                self._file_event_handlers[save_name] = FileEventHandlerConfig(
                    file_path, save_name, self._api, self._file_pusher, self._run)
            elif save_name == 'wandb-summary.json':
                # Load the summary into the syncer process for meta etc to work
                self._run.summary.load()
                self._api.get_file_stream_api().set_file_policy(save_name, file_stream.SummaryFilePolicy())
                self._file_event_handlers[save_name] = FileEventHandlerSummary(
                    file_path, save_name, self._api, self._file_pusher, self._run)
            elif save_name.startswith('media/') or save_name.startswith('code/') or save_name in ["requirements.txt", "diff.patch"]:
                # Save media files and special wandb files immediately
                self._file_event_handlers[save_name] = FileEventHandlerOverwrite(
                    file_path, save_name, self._api, self._file_pusher)
            elif save_name == meta.METADATA_FNAME:
                self._file_event_handlers[save_name] = FileEventHandlerOverwriteOnce(
                    file_path, save_name, self._api, self._file_pusher)
            else:
                Handler = FileEventHandlerOverwriteDeferred
                for policy, globs in six.iteritems(self._user_file_policies):
                    if policy == "end":
                        continue
                    for g in globs:
                        if any(save_name in p for p in glob.glob(os.path.join(self._run.dir, g))):
                            if policy == "live":
                                Handler = FileEventHandlerThrottledOverwriteMinWait
                self._file_event_handlers[save_name] = Handler(
                    file_path, save_name, self._api, self._file_pusher)
        return self._file_event_handlers[save_name]

    """ RUN MANAGEMENT STUFF """

    def mirror_stdout_stderr(self):
        """Simple STDOUT and STDERR mirroring used by _init_jupyter"""
        # TODO: Ideally we could start collecting logs without pushing
        fs_api = self._api.get_file_stream_api()
        io_wrap.SimpleTee(sys.stdout, streaming_log.TextStreamPusher(
            fs_api, util.OUTPUT_FNAME, prepend_timestamp=True))
        io_wrap.SimpleTee(sys.stderr, streaming_log.TextStreamPusher(
            fs_api, util.OUTPUT_FNAME, prepend_timestamp=True, line_prepend='ERROR'))

    def unmirror_stdout_stderr(self):
        # Python 2 tests were failing...
        if hasattr(sys.stdout, "orig_write"):
            sys.stdout.write = sys.stdout.orig_write
            sys.stderr.write = sys.stderr.orig_write

    def _get_stdout_stderr_streams(self):
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

        output_log_path = os.path.join(self._run.dir, util.OUTPUT_FNAME)
        self._output_log = WriteSerializingFile(open(output_log_path, 'wb'))

        stdout_streams = [stdout, self._output_log]
        stderr_streams = [stderr, self._output_log]

        if self._cloud:
            # Tee stdout/stderr into our TextOutputStream, which will push lines to the cloud.
            fs_api = self._api.get_file_stream_api()
            self._stdout_stream = streaming_log.TextStreamPusher(
                fs_api, util.OUTPUT_FNAME, prepend_timestamp=True)
            self._stderr_stream = streaming_log.TextStreamPusher(
                fs_api, util.OUTPUT_FNAME, line_prepend='ERROR',
                prepend_timestamp=True)

            stdout_streams.append(self._stdout_stream)
            stderr_streams.append(self._stderr_stream)

        return stdout_streams, stderr_streams

    def _close_stdout_stderr_streams(self):
        """Close output-capturing stuff. This also flushes anything left in
        the buffers.
        """

        # we don't have tee_file's in headless mode
        if self._stdout_tee.tee_file is not None:
            self._stdout_tee.tee_file.close()
        if self._stderr_tee.tee_file is not None:
            self._stderr_tee.tee_file.close()

        # TODO(adrian): we should close these even in headless mode
        # but in python 2 the read thread doesn't stop on its own
        # for some reason
        self._stdout_tee.close_join()
        self._stderr_tee.close_join()

        if self._cloud:
            # not set in dry run mode
            self._stdout_stream.close()
            self._stderr_stream.close()

        self._output_log.f.close()
        self._output_log = None

    def _setup_resume(self, resume_status):
        # write the tail of the history file
        try:
            history_tail = json.loads(resume_status['historyTail'])
            jsonlfile.write_jsonl_file(os.path.join(self._run.dir, wandb_run.HISTORY_FNAME),
                                       history_tail)
        except ValueError:
            logger.error("Couldn't parse history")
            wandb.termwarn("Couldn't load recent history, resuming may not function properly")

        # write the tail of the events file
        try:
            events_tail = json.loads(resume_status['eventsTail'])
            jsonlfile.write_jsonl_file(os.path.join(self._run.dir, wandb_run.EVENTS_FNAME),
                                       events_tail)
        except ValueError:
            logger.error("Couldn't parse system metrics / events")

        # load the previous runs summary to avoid losing it, the user process will need to load it
        self._run.summary.update(json.loads(resume_status['summaryMetrics'] or "{}"))

        # load the previous runs config
        self._run.config.load_json(json.loads(resume_status.get('config') or "{}"))
        self._run.config.persist()

        # Note: these calls need to happen after writing the files above. Because the access
        # to self._run.events below triggers events to initialize, but we need the previous
        # events to be written before that happens.

        # output.log
        self._api.get_file_stream_api().set_file_policy(
            util.OUTPUT_FNAME, file_stream.CRDedupeFilePolicy(resume_status['logLineCount']))

        # history
        self._api.get_file_stream_api().set_file_policy(
            wandb_run.HISTORY_FNAME, file_stream.JsonlFilePolicy(
                start_chunk_id=resume_status['historyLineCount']))
        self._file_event_handlers[wandb_run.HISTORY_FNAME] = FileEventHandlerTextStream(
            self._run.history.fname, wandb_run.HISTORY_FNAME, self._api, seek_end=resume_status['historyLineCount'] > 0)
        # events
        self._api.get_file_stream_api().set_file_policy(
            wandb_run.EVENTS_FNAME, file_stream.JsonlFilePolicy(
                start_chunk_id=resume_status['eventsLineCount']))
        self._file_event_handlers[wandb_run.EVENTS_FNAME] = FileEventHandlerTextStream(
            self._run.events.fname, wandb_run.EVENTS_FNAME, self._api, seek_end=resume_status['eventsLineCount'] > 0)

    def init_run(self, env=None):
        """Ensure we create a Run (Bucket) object

        We either create it now or, if the API call fails for some reason (eg.
        the network is down), we do it from a thread that we start. We hold
        off file syncing and streaming until it succeeds.

        Returns the initial step of the run, or None if we didn't create a run
        """
        io_wrap.init_sigwinch_handler()
        self._check_update_available(__version__)
        if self._output:
            wandb.termlog("Run data is saved locally in %s" % os.path.relpath(self._run.dir))

        self._system_stats.start()
        self._meta.start()
        logger.info("system metrics and metadata threads started")
        new_step = None
        if self._cloud:
            storage_id = None
            if self._run.resume != 'never':
                # DNS can hang for 60 seconds, we check for resume status in a thread
                # TODO: Ideally this thread would continue retrying in case of failure.
                # Currently we assume we're not resuming in the case of resume = auto,
                # and we throw an error in the case of resume = must.
                logger.info("checking resume status, waiting at most %d seconds" % InternalApi.HTTP_TIMEOUT)

                if not self._project:
                    raise LaunchError(
                        "resume='must' but no project is specified. Pass project to init: wandb.init(project=\"...\")")

                async_resume_status = util.async_call(self._api.run_resume_status, InternalApi.HTTP_TIMEOUT)
                resume_status, thread = async_resume_status(self._api.settings("entity"), self._project, self._run.id)

                if resume_status == None and self._run.resume == 'must':
                    if thread.is_alive():
                        raise LaunchError(
                            "resume='must' but we were unable to connect to the W&B service after %i seconds" % InternalApi.HTTP_TIMEOUT)
                    else:
                        raise LaunchError(
                            "resume='must' but run (%s) doesn't exist" % self._run.id)
                if resume_status:
                    storage_id = resume_status['id']
                    logger.info("resuming run from id: %s" % storage_id)
                    self._project = self._resolve_project_name(self._project)
                    self._setup_resume(resume_status)
                    try:
                        history = json.loads(json.loads(resume_status['historyTail'])[-1])
                    except (IndexError,ValueError):
                        history = {}
                    new_step = history.get("_step", 0)
            else:
                new_step = 0

            # DNS lookups can hang for upto 60 seconds, we wait for HTTP_TIMEOUT (10s)
            logger.info("upserting run before process can begin, waiting at most %d seconds" % InternalApi.HTTP_TIMEOUT)
            async_upsert = util.async_call(self._upsert_run, timeout=InternalApi.HTTP_TIMEOUT)
            _, self._upsert_run_thread = async_upsert(True, storage_id, env)
            if self._upsert_run_thread.is_alive():
                logger.error("Failed to connect to W&B servers after %i seconds.\
                    Letting user process proceed while attempting to reconnect." % InternalApi.HTTP_TIMEOUT)

        return new_step

    def _upsert_run(self, retry, storage_id, env):
        """Upsert the Run (ie. for the first time with all its attributes)

        Arguments:
            retry: (bool) Whether to retry if the connection fails (ie. if the backend is down).
                False is useful so we can start running the user process even when the W&B backend
                is down, and let syncing finish later.
        Returns:
            True if the upsert succeeded, False if it failed because the backend is down.
        Throws:
            LaunchError on other failures
        """
        if retry:
            num_retries = None
        else:
            num_retries = 0  # no retries because we want to let the user process run even if the backend is down

        try:
            self._run.save(
                id=storage_id, num_retries=num_retries, api=self._api)
        except CommError as e:
            logger.exception("communication error with wandb %s" % e.exc)
            # TODO: Get rid of str contains check
            if self._run.resume == 'never' and 'exists' in str(e):
                raise LaunchError(
                    "resume='never' but run (%s) exists" % self._run.id)
            else:
                # Detect bad request code -- this is usually trying to
                # create a run that has been already deleted
                if (isinstance(e.exc, requests.exceptions.HTTPError) and
                    e.exc.response.status_code == 400):
                    raise LaunchError(
                        'Failed to connect to W&B. See {} for details.'.format(
                        util.get_log_file_path()))

                if isinstance(e.exc, (requests.exceptions.HTTPError,
                                      requests.exceptions.Timeout,
                                      requests.exceptions.ConnectionError)):
                    wandb.termerror(
                        'Failed to connect to W&B. Retrying in the background.')
                    return False
                launch_error_s = 'Launch exception: {}\nTo disable wandb syncing set WANDB_MODE=dryrun'.format(e)

                raise LaunchError(launch_error_s)

        if self._output:
            if self._run.resumed:
                run_state_str = "Resuming run"
            else:
                run_state_str = "Syncing run"

            wandb.termlog("{} {}".format(run_state_str, click.style(self._run.name, fg="yellow")))
            try:
                url = self._run.get_url(self._api)
                emojis = {}
                if platform.system() != "Windows":
                    emojis = dict(star="⭐️", broom="🧹", rocket="🚀")
                project_url = self._run.get_project_url(self._api)
                wandb.termlog("{} View project at {}".format(
                    emojis.get("star", ""),
                    click.style(project_url, underline=True, fg='blue')))
                sweep_url = self._run.get_sweep_url(self._api)
                if sweep_url:
                    wandb.termlog("{} View sweep at {}".format(
                        emojis.get("broom", ""),
                        click.style(sweep_url, underline=True, fg='blue')))
                wandb.termlog("{} View run at {}".format(
                    emojis.get("rocket", ""),
                    click.style(url, underline=True, fg='blue')))
            except CommError as e:
                wandb.termwarn(e.message)
            wandb.termlog("Run `wandb off` to turn off syncing.")

        env = self._run.set_environment(environment=env)

        if wandb_env.should_save_code():
            logger.info("saving patches")
            self._api.save_patches(self._run.dir)
        if env.get("SPELL_RUN_URL"):
            self._api.sync_spell(self._run, env)
        logger.info("saving pip packages")
        self._api.save_pip(self._run.dir)
        logger.info("initializing streaming files api")
        self._api.get_file_stream_api().set_default_file_policy(
            util.OUTPUT_FNAME, file_stream.CRDedupeFilePolicy())
        self._api.get_file_stream_api().start()
        self._project = self._api.settings("project")

        # unblock file syncing and console streaming, which need the Run to have a .storage_id
        logger.info("unblocking file change observer, beginning sync with W&B servers")
        self._unblock_file_observer()

        return True

    def shutdown(self, exitcode=0):
        """Stops system stats, streaming handlers, and uploads files without output, used by wandb.monitor"""
        logger.info("shutting down system stats and metadata service")
        self._system_stats.shutdown()
        self._meta.shutdown()
        for watcher in self._tensorboard_watchers:
            watcher.shutdown()
        if self._tensorboard_consumer:
            self._tensorboard_consumer.shutdown()

        if self._run_status_checker:
            self._run_status_checker.shutdown()

        self._run.history.close()

        if self._cloud:
            logger.info("stopping streaming files and file change observer")
            self._end_file_syncing(exitcode)


    def run_user_process(self, program, args, env):
        """Launch a user process, capture its output, and sync its files to the backend.

        This returns after the process has ended and syncing is done.
        Captures ctrl-c's, signals, etc.
        """
        stdout_streams, stderr_streams = self._get_stdout_stderr_streams()

        if platform.system() == "Windows":
            # PTYs don't work in windows so we use pipes.
            self._stdout_tee = io_wrap.Tee.pipe(*stdout_streams)
            self._stderr_tee = io_wrap.Tee.pipe(*stderr_streams)
            # Seems like the following actually isn't necessary on Windows
            # TODO(adrian): we may need to do the following if we use pipes instead of PTYs
            # because Python on Unix doesn't like writing UTF-8 to files
            # tell child python interpreters we accept utf-8
            # env['PYTHONIOENCODING'] = 'UTF-8'
        else:
            self._stdout_tee = io_wrap.Tee.pty(*stdout_streams)
            self._stderr_tee = io_wrap.Tee.pty(*stderr_streams)

        command = [program] + list(args)
        runner = util.find_runner(program)
        if runner:
            command = runner + command
        if platform.system() == "Windows":
            command = ' '.join(windows.quote_arg(arg) for arg in command)
        else:
            command = ' '.join(six.moves.shlex_quote(arg) for arg in command)
        self._stdout_stream.write_string(command + "\n\n")

        try:
            self.proc = subprocess.Popen(
                command,
                env=env,
                stdout=self._stdout_tee.tee_file,
                stderr=self._stderr_tee.tee_file,
                shell=True,
            )
            self._run.pid = self.proc.pid
        except (OSError, IOError):
            raise Exception('Could not find program: %s' % command)

        self._sync_etc()

    def wrap_existing_process(self, pid, stdout_read_fd, stderr_read_fd, port=None):
        """Do syncing, etc. for an already-running process.

        This returns after the process has ended and syncing is done.
        Captures ctrl-c's, signals, etc.
        """
        stdout_read_file = os.fdopen(stdout_read_fd, 'rb')
        stderr_read_file = os.fdopen(stderr_read_fd, 'rb')
        stdout_streams, stderr_streams = self._get_stdout_stderr_streams()
        self._stdout_tee = io_wrap.Tee(stdout_read_file, *stdout_streams)
        self._stderr_tee = io_wrap.Tee(stderr_read_file, *stderr_streams)

        self.proc = Process(pid)
        self._run.pid = pid
        logger.info("wrapping existing process %i" % pid)

        try:
            self.init_run()
        except LaunchError as e:
            logger.exception("catostrophic launch error")
            wandb.termerror(str(e))
            util.sentry_exc(e)
            self._socket.launch_error()
            return

        if io_wrap.SIGWINCH_HANDLER is not None:
            # SIGWINCH_HANDLER (maybe) gets set in self.init_run()
            io_wrap.SIGWINCH_HANDLER.add_fd(stdout_read_fd)
            io_wrap.SIGWINCH_HANDLER.add_fd(stderr_read_fd)

        # Signal the main process that we're all hooked up
        logger.info("informing user process we are ready to proceed")
        self._socket.ready()

        self._sync_etc(headless=True)

    def _check_update_available(self, current_version):
        timeout = 2  # Two seconds.
        pypi_url = 'https://pypi.org/pypi/wandb/json'
        try:
            data = requests.get(pypi_url, timeout=timeout).json()
            latest_version = data['info']['version']
        except:
            # Any issues whatsoever, just skip the latest version check.
            return

        # Return if no update is available
        if parse_version(latest_version) <= parse_version(current_version):
            return

        # A new version is available!
        wandb.termlog(
            "Wandb version %s is available!  To upgrade, please run:\n $ pip install wandb --upgrade" % latest_version)

    def update_user_file_policy(self, policy):
        with self._file_policy_lock:
            for path in glob.glob(policy["glob"]):
                save_name = os.path.relpath(path, self._run.dir)
                # Remove the existing handler if we haven't already made it live
                current = self._file_event_handlers.get(save_name)
                is_live = isinstance(current, FileEventHandlerThrottledOverwriteMinWait)
                if current and policy["policy"] == "live" and not is_live:
                    del self._file_event_handlers[save_name]
            self._user_file_policies[policy["policy"]].append(policy["glob"])

    def start_tensorboard_watcher(self, logdir, save=True):
        try:
            from wandb.tensorboard.watcher import Watcher, Consumer
            dirs = [logdir] + [w.logdir for w in self._tensorboard_watchers]
            rootdir = os.path.dirname(os.path.commonprefix(dirs))
            if os.path.isfile(logdir):
                filename = os.path.basename(logdir)
            else:
                filename = ""
            # Tensorboard loads all tfevents files in a directory and prepends
            # their values with the path.  Passing namespace to log allows us
            # to nest the values in wandb
            namespace = logdir.replace(filename, "").replace(
                rootdir, "").strip(os.sep)
            # TODO: revisit this heuristic, it exists because we don't know the
            # root log directory until more than one tfevents file is written to
            if len(dirs) == 1 and namespace not in ["train", "validation"]:
                namespace = None
            with self._tensorboard_lock:
                self._tensorboard_watchers.append(Watcher(logdir, self._watcher_queue, namespace=namespace, save=save))
                if self._tensorboard_consumer is None:
                    self._tensorboard_consumer = Consumer(self._watcher_queue)
                    self._tensorboard_consumer.start()
            self._tensorboard_watchers[-1].start()
            return self._tensorboard_watchers
        except ImportError:
            wandb.termerror("Couldn't import tensorboard, not streaming events. Run `pip install tensorboard`")


    def _sync_etc(self, headless=False):
        # Ignore SIGQUIT (ctrl-\). The child process will handle it, and we'll
        # exit when the child process does.
        #
        # We disable these signals after running the process so the child doesn't
        # inherit this behaviour.
        try:
            signal.signal(signal.SIGQUIT, signal.SIG_IGN)
        except (AttributeError, ValueError):  # SIGQUIT doesn't exist on windows, we can't use signal.signal in threads for tests
            pass

        # When not running in agent mode, start a status checker.
        # TODO(adrnswanberg): Remove 'stop' command checking in agent code,
        # and unconditionally start the status checker.
        if self._run.sweep_id is None:
            def stop_handler():
                if isinstance(self.proc, Process):
                    # self.proc is a `Process` whenever we're the child process.
                    self.proc.interrupt()
                else:
                    sig = signal.SIGINT
                    # We only check for windows in this block because on windows we
                    # always use `wandb run` (meaning we're the parent process).
                    if platform.system() == "Windows":
                        sig = signal.CTRL_C_EVENT # pylint: disable=no-member
                    self.proc.send_signal(sig)

            if self._cloud:
                self._run_status_checker = RunStatusChecker(
                    self._run, self._api, stop_requested_handler=stop_handler)

        # Add a space before user output
        wandb.termlog()

        if wandb_env.get_show_run():
            try:
                webbrowser.open_new_tab(self._run.get_url(self._api))
            except CommError:
                pass

        exitcode = None
        try:
            payload = b''
            parse = False
            logger.info("entering loop for messages from user process")
            while True:
                res = bytearray()
                # We received multiple messages from the last socket read
                if payload.find(b'\0') != -1:
                    res = payload
                    payload = b''
                else:
                    try:
                        res = self._socket.recv(1024)
                    except socket.error as e:
                        # https://stackoverflow.com/questions/16094618/python-socket-recv-and-signals
                        if e.errno == errno.EINTR or isinstance(e, socket.timeout):
                            pass
                        else:
                            raise e
                term = res.find(b'\0')
                if term != -1:
                    payload += res[:term]
                    parse = True
                else:
                    payload += res
                if parse:
                    logger.info("received message from user process: %s" % payload.decode('utf8'))
                    try:
                        parsed = json.loads(payload.decode('utf8'))
                    except ValueError:
                        parsed = {}
                    if parsed.get("exitcode") is not None:
                        exitcode = parsed["exitcode"]
                        break
                    elif parsed.get("save_policy"):
                        self.update_user_file_policy(parsed["save_policy"])
                        payload = b''
                        parse = False
                    elif parsed.get("tensorboard"):
                        if parsed["tensorboard"].get("logdir"):
                            self.start_tensorboard_watcher(parsed["tensorboard"]["logdir"], parsed["tensorboard"]["save"])
                        payload = b''
                        parse = False
                    else:
                        message = "Invalid message received from child process: %s" % str(
                            payload)
                        wandb.termerror(message)
                        util.sentry_exc(message)
                        break
                    new_start = term + 1
                    # There's more to parse, add the remaining bytes
                    if len(res) > new_start:
                        payload = res[new_start:]
                else:
                    exitcode = self.proc.poll()
                    if exitcode is not None:
                        break
                    time.sleep(1)
        except KeyboardInterrupt:
            logger.info("process received interrupt signal, shutting down")
            exitcode = 255
            if headless:
                wandb.termlog('Ctrl-c pressed.')
            else:
                wandb.termlog(
                    'Ctrl-c pressed; waiting for program to end. Press ctrl-c again to kill it.')
                try:
                    logger.info("waiting for process to finish")
                    while self.proc.poll() is None:
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    pass

                if self.proc.poll() is None:
                    logger.info("killing user process")
                    wandb.termlog('Program still alive. Killing it.')
                    try:
                        self.proc.kill()
                    except OSError:
                        pass

        """TODO(adrian): garbage that appears in the logs sometimes

        Exception ignored in: <bound method Popen.__del__ of <subprocess.Popen object at 0x111adce48>>
        Traceback (most recent call last):
          File "/Users/adrian/.pyenv/versions/3.6.0/Python.framework/Versions/3.6/lib/python3.6/subprocess.py", line 760, in __del__
        AttributeError: 'NoneType' object has no attribute 'warn'
        """

        if exitcode is None:
            exitcode = 254
            wandb.termlog(
                'Killing program failed; syncing files anyway. Press ctrl-c to abort syncing.')
        else:
            if exitcode == 0:
                wandb.termlog('Program ended successfully.')
                resume_path = os.path.join(wandb.wandb_dir(), wandb_run.RESUME_FNAME)
                if os.path.exists(resume_path):
                    os.remove(resume_path)
            else:
                wandb.termlog(
                    'Program failed with code %d. Press ctrl-c to abort syncing.' % exitcode)

        self._meta.data["exitcode"] = exitcode
        if exitcode == 0:
            self._meta.data["state"] = "finished"
        elif exitcode == 255:
            self._meta.data["state"] = "killed"
        else:
            self._meta.data["state"] = "failed"

        # TODO(adrian): these can be slow to complete (due to joining?)
        logger.info("closing log streams and sending exitcode to W&B")
        self._close_stdout_stderr_streams()
        self.shutdown(exitcode)

        crash_nosync_time = wandb_env.get_crash_nosync_time(self.CRASH_NOSYNC_TIME)
        # If we're not syncing to the cloud, we're done
        if not self._cloud:
            wandb.termlog("You can sync this run to the cloud by running: ")
            wandb.termlog("wandb sync %s" % os.path.relpath(self._run.dir))
            sys.exit(exitcode)
        elif exitcode != 0 and crash_nosync_time and time.time() - START_TIME < crash_nosync_time:
            wandb.termlog("Process crashed early, not syncing files")
            logger.info("process only ran for %d seconds, not syncing files" % (time.time() - START_TIME))
            sys.exit(exitcode)

        # Show run summary/history
        self._run.summary.load()
        summary = self._run.summary._json_dict
        if len(summary):
            logger.info("rendering summary")
            wandb.termlog('Run summary:')
            max_len = max([len(k) for k in summary.keys()])
            format_str = '  {:>%s} {}' % max_len
            for k, v in summary.items():
                # arrays etc. might be too large. for now we just don't print them
                if isinstance(v, six.string_types):
                    if len(v) >= 20:
                        v = v[:20] + '...'
                    wandb.termlog(format_str.format(k, v))
                elif isinstance(v, numbers.Number):
                    wandb.termlog(format_str.format(k, v))

        self._run.history.load()
        history_keys = self._run.history.keys()
        # Only print sparklines if the terminal is utf-8
        # In some python 2.7 tests sys.stdout is a 'cStringIO.StringO' object 
        #   which doesn't have the attribute 'encoding'
        if len(history_keys) and hasattr(sys.stdout, 'encoding') and sys.stdout.encoding == "UTF_8":
            logger.info("rendering history")
            wandb.termlog('Run history:')
            max_len = max([len(k) for k in history_keys])
            for key in history_keys:
                vals = util.downsample(self._run.history.column(key), 40)
                if any((not isinstance(v, numbers.Number) for v in vals)):
                    continue
                line = sparkline.sparkify(vals)
                format_str = u'  {:>%s} {}' % max_len
                wandb.termlog(format_str.format(key, line))

        wandb_files = set([save_name for save_name in self._file_pusher.files() if util.is_wandb_file(save_name)])
        media_files = set([save_name for save_name in self._file_pusher.files() if save_name.startswith('media')])
        other_files = set(self._file_pusher.files()) - wandb_files - media_files
        logger.info("syncing files to cloud storage")
        if other_files:
            wandb.termlog('Syncing files in %s:' % os.path.relpath(self._run.dir))
            for save_name in sorted(other_files):
                wandb.termlog('  %s' % save_name)
            wandb.termlog('plus {} W&B file(s) and {} media file(s)'.format(len(wandb_files), len(media_files)))
        else:
            wandb.termlog('Syncing {} W&B file(s) and {} media file(s)'.format(len(wandb_files), len(media_files)))

        self._file_pusher.update_all_files()
        self._file_pusher.print_status()

        try:
            url = self._run.get_url(self._api)
            wandb.termlog('Synced{} {}'.format(format_run_name(self._run), url))
            logger.info("syncing complete: %s" % url)
        except CommError as e:
            wandb.termwarn(e.message)
        sys.exit(exitcode)
