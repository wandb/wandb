import errno
import json
import logging
import os
import psutil
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

import click
from shortuuid import ShortUUID
import six
from six.moves import queue
import requests
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import webbrowser

import wandb
from wandb.apis.file_stream import BinaryFilePolicy, CRDedupeFilePolicy, DefaultFilePolicy, OverwriteFilePolicy
from wandb import env
from wandb import Error
from wandb import io_wrap
from wandb import jsonlfile
from wandb import file_pusher
from wandb import meta
from wandb.core import START_TIME
import wandb.rwlock
from wandb import sparkline
from wandb import stats
from wandb import streaming_log
from wandb import util
from wandb import wandb_config as config
from wandb import wandb_run
from wandb import wandb_socket


logger = logging.getLogger(__name__)


OUTPUT_FNAME = 'output.log'
DEBUG_FNAME = 'wandb-debug.log'


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

    def stop(self):
        self._file.seek(0)
        self.running = False
        self._thread.join()


class FileEventHandler(object):
    def __init__(self, file_path, save_name, api):
        self.file_path = file_path
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
        # Tell file_pusher to copy the file, we want to allow the user to modify the
        # original while this one is uploading (modifying while uploading seems to
        # cause a hang somewhere in the google upload code, until the server times out)
        self._file_pusher.file_changed(
            self.save_name, self.file_path, copy=True)


class FileEventHandlerOverwriteDeferred(FileEventHandler):
    def __init__(self, file_path, save_name, api, file_pusher, *args, **kwargs):
        super(FileEventHandlerOverwriteDeferred, self).__init__(
            file_path, save_name, api, *args, **kwargs)
        self._file_pusher = file_pusher

    def finish(self):
        self._file_pusher.file_changed(self.save_name, self.file_path)


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
            config_dict = yaml.load(open(self.file_path))
        except yaml.parser.ParserError:
            wandb.termlog(
                "Unable to parse config file; probably being modified by user process?")
            return

        # TODO(adrian): ensure the file content will exactly match Bucket.config
        # ie. push the file content as a string
        self._api.upsert_run(id=self._run.storage_id, config=config_dict)
        self._file_pusher.file_changed(
            self.save_name, self.file_path, copy=True)
        self._last_sent = time.time()

    def finish(self):
        if self._thread:
            self._thread.join()
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
        self._api.get_file_stream_api().push(self.save_name, open(self.file_path).read())

    def finish(self):
        self._file_pusher.file_changed(self.save_name, self.file_path)


class FileEventHandlerTextStream(FileEventHandler):
    def __init__(self, *args, **kwargs):
        self._seek_end = kwargs.pop('seek_end', None)
        super(FileEventHandlerTextStream, self).__init__(*args, **kwargs)
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


class RunManager(object):
    """Manages a run's process, wraps its I/O, and synchronizes its files.
    """

    def __init__(self, api, run, project=None, tags=[], cloud=True, job_type="train", output=True, port=None):
        self._api = api
        self._run = run
        self._cloud = cloud
        self._port = port

        self._project = project if project else api.settings("project")
        self._tags = tags
        self._watch_dir = self._run.dir

        self._config = run.config
        self.job_type = job_type
        self.url = self._run.get_url(api)

        # We lock this when the backend is down so Watchdog will keep track of all
        # the file events that happen. Then, when the backend comes back up, we unlock
        # it so all the outstanding events will get handled properly. Watchdog's queue
        # only keeps at most one event per file.
        # Counterintuitively, we use the "reader" locking to guard writes to the W&B
        # backend, and the "writer" locking to indicate that the backend is down. That
        # way, users of the W&B API won't block each other, but can all be
        # blocked by grabbing a "writer" lock.
        self._file_event_lock = wandb.rwlock.RWLock()
        # It starts acquired. We release it when we want to allow the events to happen.
        # (ie. after the Run is successfully created)
        self._file_event_lock.writer_enters()

        self._event_handlers = {}

        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self._on_file_created
        self._handler.on_modified = self._on_file_modified
        self._handler.on_moved = self._on_file_moved
        self._handler._patterns = [
            os.path.join(self._watch_dir, os.path.normpath('*'))]
        # Ignore hidden files/folders and output.log because we stream it specially
        self._handler._ignore_patterns = [
            '*/.*',
            '*.tmp',
            os.path.join(self._run.dir, OUTPUT_FNAME),
            os.path.join(self._run.dir, DEBUG_FNAME)
        ]
        for glob in self._api.settings("ignore_globs"):
            self._handler._ignore_patterns.append(
                os.path.join(self._run.dir, glob))

        self._observer = Observer()
        self._observer.schedule(self._handler, self._watch_dir, recursive=True)

        self._stats = stats.Stats()
        # Calling .start() on _meta and _system_stats will spin a thread that reports system stats every 30 seconds
        self._system_stats = stats.SystemStats(run, api)
        self._meta = meta.Meta(api, self._run.dir)
        self._meta.data["jobType"] = job_type
        if self._run.program:
            self._meta.data["program"] = self._run.program
        self._file_pusher = file_pusher.FilePusher(self._push_function)

        self._socket = wandb_socket.Client(self._port)

        logger.debug("Initialized sync for %s/%s", self._project, self._run.id)
        # Manually initialize the debug handler
        self._get_handler(os.path.join(
            self._run.dir, DEBUG_FNAME), DEBUG_FNAME).on_created()

        if self._cloud:
            self._observer.start()

            self._api.save_patches(self._watch_dir)

            if output:
                wandb.termlog("Syncing %s" % self.url)
                wandb.termlog("Run `wandb off` to turn off syncing.")
                wandb.termlog("Local directory: %s" % os.path.relpath(run.dir))

            self._api.get_file_stream_api().set_file_policy(
                OUTPUT_FNAME, CRDedupeFilePolicy())

    """ FILE SYNCING / UPLOADING STUFF """

    # TODO: limit / throttle the number of adds / pushes
    def _on_file_created(self, event):
        logger.info('file/dir created: %s', event.src_path)
        if os.path.isdir(event.src_path):
            return None
        save_name = os.path.relpath(event.src_path, self._watch_dir)
        self._file_event_lock.await_readable()
        self._get_handler(event.src_path, save_name).on_created()

    def _on_file_modified(self, event):
        logger.info('file/dir modified: %s', event.src_path)
        if os.path.isdir(event.src_path):
            return None
        save_name = os.path.relpath(event.src_path, self._watch_dir)
        self._file_event_lock.await_readable()
        self._get_handler(event.src_path, save_name).on_modified()

    def _on_file_moved(self, event):
        logger.info('file/dir moved: %s -> %s',
                    event.src_path, event.dest_path)
        if os.path.isdir(event.dest_path):
            return None
        old_save_name = os.path.relpath(event.src_path, self._watch_dir)
        new_save_name = os.path.relpath(event.dest_path, self._watch_dir)
        self._file_event_lock.await_readable()

        # We have to move the existing file handler to the new name, and update the stats
        handler = self._get_handler(event.src_path, old_save_name)
        self._event_handlers[new_save_name] = handler
        del self._event_handlers[old_save_name]
        self._stats.rename_file(event.src_path, event.dest_path)

        handler.on_renamed(event.dest_path, new_save_name)

    def _get_handler(self, file_path, save_name):
        if not save_name.startswith("media/") and save_name not in [
                'wandb-history.jsonl', 'wandb-events.jsonl', 'wandb-summary.json']:
            # Don't show stats on media files
            self._stats.update_file(file_path)
        if save_name not in self._event_handlers:
            if save_name == 'wandb-history.jsonl':
                self._event_handlers['wandb-history.jsonl'] = FileEventHandlerTextStream(
                    file_path, 'wandb-history.jsonl', self._api)
            elif save_name == 'wandb-events.jsonl':
                self._event_handlers['wandb-events.jsonl'] = FileEventHandlerTextStream(
                    file_path, 'wandb-events.jsonl', self._api)
            # Don't try to stream tensorboard files for now.
            # elif 'tfevents' in save_name:
            #    # TODO: This is hard-coded, but we want to give users control
            #    # over streaming files (or detect them).
            #    self._api.get_file_stream_api().set_file_policy(save_name,
            #                                                    BinaryFilePolicy())
            #    self._event_handlers[save_name] = FileEventHandlerBinaryStream(
            #        file_path, save_name, self._api)
            # Overwrite handler (non-deferred) has a bug, wherein if the file is truncated
            # during upload, the request to Google hangs (at least, this is my working
            # theory). So for now we defer uploading everything til the end of the run.
            # TODO: send wandb-summary during run. One option is to copy to a temporary
            # file before uploading.
            elif save_name == config.FNAME:
                self._event_handlers[save_name] = FileEventHandlerConfig(
                    file_path, save_name, self._api, self._file_pusher, self._run)
            elif save_name == 'wandb-summary.json':
                # Load the summary into the syncer process for meta etc to work
                self._run.summary.load()
                self._api.get_file_stream_api().set_file_policy(save_name, OverwriteFilePolicy())
                self._event_handlers[save_name] = FileEventHandlerSummary(
                    file_path, save_name, self._api, self._file_pusher, self._run)
            elif save_name.startswith('media/'):
                # Save media files immediately
                self._event_handlers[save_name] = FileEventHandlerOverwrite(
                    file_path, save_name, self._api, self._file_pusher)
            else:
                self._event_handlers[save_name] = FileEventHandlerOverwriteDeferred(
                    file_path, save_name, self._api, self._file_pusher)
        return self._event_handlers[save_name]

    def _finish_handlers(self):
        # TODO: there was a case where _event_handlers was getting modified in the loop.
        for handler in list(self._event_handlers.values()):
            handler.finish()

    def _push_function(self, save_name, path):
        try:
            with open(path, 'rb') as f:
                self._api.push(self._project, {save_name: f}, run=self._run.id,
                               progress=lambda _, total: self._stats.update_progress(path, total))
        except (OSError, IOError):
            pass

    """ RUN MANAGEMENT STUFF """

    def mirror_stdout_stderr(self):
        """Simple STDOUT and STDERR mirroring used by _init_jupyter"""
        # TODO: Ideally we could start collecting logs without pushing
        fs_api = self._api.get_file_stream_api()
        io_wrap.SimpleTee(sys.stdout, streaming_log.TextStreamPusher(
            fs_api, OUTPUT_FNAME, prepend_timestamp=True))
        io_wrap.SimpleTee(sys.stderr, streaming_log.TextStreamPusher(
            fs_api, OUTPUT_FNAME, prepend_timestamp=True, line_prepend='ERROR'))

    def unmirror_stdout_stderr(self):
        sys.stdout.write = sys.stdout.orig_write
        sys.stderr.write = sys.stderr.orig_write

    def _get_stdout_stderr_streams(self):
        """Sets up STDOUT and STDERR streams. Only call this once."""
        if six.PY2 or not hasattr(sys.stdout, "buffer"):
            if hasattr(sys.stdout, "fileno") and not os.getenv("WANDB_TEST"):
                stdout = os.fdopen(sys.stdout.fileno(), "w+", 0)
                stderr = os.fdopen(sys.stderr.fileno(), "w+", 0)
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

        output_log_path = os.path.join(self._run.dir, OUTPUT_FNAME)
        self._output_log = WriteSerializingFile(open(output_log_path, 'wb'))

        stdout_streams = [stdout, self._output_log]
        stderr_streams = [stderr, self._output_log]

        if self._cloud:
            # Tee stdout/stderr into our TextOutputStream, which will push lines to the cloud.
            fs_api = self._api.get_file_stream_api()
            self._stdout_stream = streaming_log.TextStreamPusher(
                fs_api, OUTPUT_FNAME, prepend_timestamp=True,
                lock_function=self._file_event_lock.reader_enters)
            self._stderr_stream = streaming_log.TextStreamPusher(
                fs_api, OUTPUT_FNAME, line_prepend='ERROR',
                prepend_timestamp=True,
                lock_function=self._file_event_lock.reader_enters)

            stdout_streams.append(self._stdout_stream)
            stderr_streams.append(self._stderr_stream)

        return stdout_streams, stderr_streams

    def _close_stdout_stderr_streams(self, exitcode):
        self._output_log.f.close()
        self._output_log = None

        # Close output-capturing stuff. This also flushes anything left in the buffers.
        if self._stdout_tee.tee_file is not None:
            # we don't have tee_file's in headless mode
            self._stdout_tee.tee_file.close()
            # TODO(adrian): we should close these even in headless mode
            # but in python 2 the read thread doesn't stop on its own
            # for some reason
            self._stdout_tee.close_join()
        if self._stderr_tee.tee_file is not None:
            self._stderr_tee.tee_file.close()
            self._stderr_tee.close_join()

        if self._cloud:
            # not set in dry run mode
            self._stdout_stream.close()
            self._stderr_stream.close()
            self._api.get_file_stream_api().finish(exitcode)
            # Ensures we get a new file stream thread
            self._api._file_stream_api = None

    def _setup_resume(self, resume_status):
        # write the tail of the history file
        try:
            history_tail = json.loads(resume_status['historyTail'])
            jsonlfile.write_jsonl_file(os.path.join(self._run.dir, wandb_run.HISTORY_FNAME),
                                       history_tail)
        except ValueError:
            print("warning: couldn't load recent history")

        # write the tail of the events file
        try:
            events_tail = json.loads(resume_status['eventsTail'])
            jsonlfile.write_jsonl_file(os.path.join(self._run.dir, wandb_run.EVENTS_FNAME),
                                       events_tail)
        except ValueError:
            print("warning: couldn't load recent events")

        # Note: these calls need to happen after writing the files above. Because the access
        # to self._run.events below triggers events to initialize, but we need the previous
        # events to be written before that happens.

        # output.log
        self._api.get_file_stream_api().set_file_policy(
            OUTPUT_FNAME, CRDedupeFilePolicy(resume_status['logLineCount']))

        # history
        self._api.get_file_stream_api().set_file_policy(
            wandb_run.HISTORY_FNAME, DefaultFilePolicy(
                start_chunk_id=resume_status['historyLineCount']))
        self._event_handlers[wandb_run.HISTORY_FNAME] = FileEventHandlerTextStream(
            self._run.history.fname, wandb_run.HISTORY_FNAME, self._api, seek_end=True)

        # events
        self._api.get_file_stream_api().set_file_policy(
            wandb_run.EVENTS_FNAME, DefaultFilePolicy(
                start_chunk_id=resume_status['eventsLineCount']))
        self._event_handlers[wandb_run.EVENTS_FNAME] = FileEventHandlerTextStream(
            self._run.events.fname, wandb_run.EVENTS_FNAME, self._api, seek_end=True)

    def init_run(self, env=None):
        io_wrap.init_sigwinch_handler()
        self._system_stats.start()
        self._meta.start()
        self._api.get_file_stream_api().start()
        if self._cloud:
            storage_id = None
            if self._run.resume != 'never':
                resume_status = self._api.run_resume_status(project=self._api.settings("project"),
                                                            entity=self._api.settings(
                                                                "entity"),
                                                            name=self._run.id)
                if resume_status == None and self._run.resume == 'must':
                    raise LaunchError(
                        "resume='must' but run (%s) doesn't exist" % self._run.id)
                if resume_status:
                    print('Resuming run: %s' % self._run.get_url(self._api))
                    self._setup_resume(resume_status)
                    storage_id = resume_status['id']

            if not self._upsert_run(False, storage_id, env):
                self._upsert_run_thread = threading.Thread(
                    target=self._upsert_run, args=(True, storage_id, env))
                self._upsert_run_thread.daemon = True
                self._upsert_run_thread.start()

    def shutdown(self, exitcode=0):
        """Stops system stats, streaming handlers, and uploads files without output, used by wandb.monitor"""
        self._system_stats.shutdown()
        self._meta.shutdown()
        self._stop_watchdog()
        self._finish_handlers()
        self._file_pusher.shutdown()
        self._api.get_file_stream_api().finish(exitcode)
        # Ensures we get a new file stream thread
        self._api._file_stream_api = None

    def _stop_watchdog(self):
        try:
            # avoid hanging if we crashed before the observer was started
            if self._observer.is_alive():
                self._observer.stop()
                self._observer.join()
        # TODO: py2 TypeError: PyCObject_AsVoidPtr called with null pointer
        except TypeError:
            pass
        # TODO: py3 SystemError: <built-in function stop> returned a result with an error set
        except SystemError:
            pass

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
            upsert_result = self._run.save(
                id=storage_id, num_retries=num_retries, job_type=self.job_type, api=self._api)
        except wandb.apis.CommError as e:
            # TODO: Get rid of str contains check
            if self._run.resume == 'never' and 'exists' in str(e):
                raise LaunchError(
                    "resume='never' but run (%s) exists" % self._run.id)
            else:
                if isinstance(e.exc, (requests.exceptions.HTTPError,
                                      requests.exceptions.Timeout,
                                      requests.exceptions.ConnectionError)):
                    wandb.termerror(
                        'Failed to connect to W&B. Retrying in the background.')
                    return False

                raise LaunchError(
                    'Launch exception: {}, see {} for details.  To disable wandb set WANDB_MODE=dryrun'.format(e, util.get_log_file_path()))

        self._run.set_environment(environment=env)

        # unblock file syncing and console streaming, which need the Run to have a .storage_id
        self._file_event_lock.writer_leaves()

        return True

    def run_user_process(self, program, args, env):
        """Launch a user process, capture its output, and sync its files to the backend.

        This returns after the process has ended and syncing is done.
        Captures ctrl-c's, signals, etc.
        """
        stdout_streams, stderr_streams = self._get_stdout_stderr_streams()

        if sys.platform == "win32":
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

        self._stdout_stream.write_string(" ".join(psutil.Process(
            os.getpid()).cmdline()) + "\n\n")

        command = [program] + list(args)
        runner = util.find_runner(program)
        if runner:
            command = runner + command
        command = ' '.join(six.moves.shlex_quote(arg) for arg in command)

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

        try:
            self.init_run()
        except LaunchError as e:
            wandb.termerror(str(e))
            util.sentry_exc(e)
            self._socket.launch_error()
            return

        if io_wrap.SIGWINCH_HANDLER is not None:
            # SIGWINCH_HANDLER (maybe) gets set in self.init_run()
            io_wrap.SIGWINCH_HANDLER.add_fd(stdout_read_fd)
            io_wrap.SIGWINCH_HANDLER.add_fd(stderr_read_fd)

        # Signal the main process that we're all hooked up
        self._socket.ready()

        self._sync_etc(headless=True)

    def _sync_etc(self, headless=False):
        # Ignore SIGQUIT (ctrl-\). The child process will # handle it, and we'll
        # exit when the child process does.
        #
        # We disable these signals after running the process so the child doesn't
        # inherit this behaviour.
        try:
            signal.signal(signal.SIGQUIT, signal.SIG_IGN)
        except AttributeError:  # SIGQUIT doesn't exist on windows
            pass

        if self._api.update_available:
            wandb.termlog(
                "An update is available!  To upgrade, please run:\n $ pip install wandb --upgrade")
        # Add a space before user output
        wandb.termlog()

        if env.get_show_run():
            webbrowser.open_new_tab(self._run.get_url(self._api))

        exitcode = None
        try:
            while True:
                res = bytearray()
                try:
                    res = self._socket.recv(2)
                except socket.error as e:
                    # https://stackoverflow.com/questions/16094618/python-socket-recv-and-signals
                    if e.errno == errno.EINTR or isinstance(e, socket.timeout):
                        pass
                    else:
                        raise e
                if len(res) == 2 and res[0] == 2:
                    exitcode = res[1]
                    break
                elif len(res) > 0:
                    message = "Invalid message received from child process: %s" % str(
                        res)
                    wandb.termerror(message)
                    util.sentry_message(message)
                    break
                else:
                    exitcode = self.proc.poll()
                    if exitcode is not None:
                        break
                    time.sleep(1)
        except KeyboardInterrupt:
            exitcode = 255
            if headless:
                wandb.termlog('Ctrl-c pressed.')
            else:
                wandb.termlog(
                    'Ctrl-c pressed; waiting for program to end. Press ctrl-c again to kill it.')
                try:
                    while self.proc.poll() is None:
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    pass

                if self.proc.poll() is None:
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
                wandb.termlog('Program ended.')
            else:
                wandb.termlog(
                    'Program failed with code %d. Press ctrl-c to abort syncing.' % exitcode)
        #termlog('job (%s) Process exited with code: %s' % (program, exitcode))

        self._meta.data["exitcode"] = exitcode
        if exitcode == 0:
            self._meta.data["state"] = "finished"
        elif exitcode == 255:
            self._meta.data["state"] = "killed"
        else:
            self._meta.data["state"] = "failed"

        self._meta.shutdown()
        self._system_stats.shutdown()

        if exitcode != 0 and time.time() - START_TIME < 30:
            wandb.termlog("Process crashed early, not syncing files")
            sys.exit(exitcode)

        # TODO: these can be slow to complete
        self._close_stdout_stderr_streams(exitcode)

        # If we're not syncing to the cloud, we're done
        if not self._cloud:
            sys.exit(exitcode)

        # Show run summary/history
        self._run.summary.load()
        summary = self._run.summary._summary
        if len(summary):
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
        if len(history_keys):
            wandb.termlog('Run history:')
            max_len = max([len(k) for k in history_keys])
            for key in history_keys:
                vals = util.downsample(self._run.history.column(key), 40)
                if any((not isinstance(v, numbers.Number) for v in vals)):
                    continue
                line = sparkline.sparkify(vals)
                format_str = u'  {:>%s} {}' % max_len
                wandb.termlog(format_str.format(key, line))

        if self._run.has_examples:
            wandb.termlog('Saved %s examples' % self._run.examples.count())

        wandb.termlog('Waiting for final file modifications.')
        # This is a a heuristic delay to catch files that were written just before
        # the end of the script.
        # TODO: ensure we catch all saved files.
        # TODO(adrian): do we need this?
        time.sleep(1)
        self._stop_watchdog()

        self._finish_handlers()
        self._file_pusher.finish()

        wandb.termlog('Syncing files in %s:' %
                      os.path.relpath(self._watch_dir))
        for file_path in self._stats.files():
            wandb.termlog('  %s' % os.path.relpath(file_path, self._watch_dir))
        step = 0
        spinner_states = ['-', '\\', '|', '/']
        stop = False
        self._stats.update_all_files()
        while True:
            if not self._file_pusher.is_alive():
                stop = True
            summary = self._stats.summary()
            line = (' %(completed_files)s of %(total_files)s files,'
                    ' %(uploaded_bytes).03f of %(total_bytes).03f bytes uploaded\r' % summary)
            line = spinner_states[step % 4] + line
            step += 1
            wandb.termlog(line, newline=False)
            if stop:
                break
            time.sleep(0.25)
            #print('FP: ', self._file_pusher._pending, self._file_pusher._jobs)
        # clear progress line.
        wandb.termlog(' ' * 79)

        # Check md5s of uploaded files against what's on the file system.
        # TODO: We're currently using the list of uploaded files as our source
        #     of truth, but really we should use the files on the filesystem
        #     (ie if we missed a file this wouldn't catch it).
        # This polls the server, because there a delay between when the file
        # is done uploading, and when the datastore gets updated with new
        # metadata via pubsub.
        wandb.termlog('Verifying uploaded files... ', newline=False)
        error = False
        mismatched = None
        for delay_base in range(4):
            mismatched = []
            download_urls = self._api.download_urls(
                self._project, run=self._run.id)
            for fname, info in download_urls.items():
                if fname == 'wandb-history.h5' or OUTPUT_FNAME:
                    continue
                local_path = os.path.join(self._watch_dir, fname)
                local_md5 = util.md5_file(local_path)
                if local_md5 != info['md5']:
                    mismatched.append((local_path, local_md5, info['md5']))
            if not mismatched:
                break
            wandb.termlog('  Retrying after %ss' % (delay_base**2))
            time.sleep(delay_base ** 2)

        if mismatched:
            print('')
            error = True
            for local_path, local_md5, remote_md5 in mismatched:
                wandb.termerror(
                    '%s (%s) did not match uploaded file (%s) md5' % (
                        local_path, local_md5, remote_md5))
        else:
            print('verified!')

        if error:
            message = 'Sync failed %s' % self.url
            wandb.termerror(message)
            util.sentry_message(message)
        else:
            wandb.termlog('Synced %s' % self.url)
        sys.exit(exitcode)
