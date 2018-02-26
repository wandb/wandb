import errno
import psutil
import os
import signal
import socket
import stat
import subprocess
import sys
import time
import re
from tempfile import NamedTemporaryFile
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from shortuuid import ShortUUID
from .config import Config
import logging
import threading

import six
from six.moves import queue
import click

import wandb
from wandb import Error
from wandb import io_wrap
from wandb import file_pusher
from wandb import sparkline
from wandb import stats
from wandb import streaming_log
from wandb import util
from wandb import wandb_run
from wandb import wandb_socket
from wandb import meta
import wandb.api
from .api import BinaryFilePolicy, CRDedupeFilePolicy
logger = logging.getLogger(__name__)


OUTPUT_FNAME = 'output.log'


class FileTailer(object):
    def __init__(self, path, on_read_fn, binary=False):
        self._path = path
        mode = 'r'
        if binary:
            mode = 'rb'
        self._file = open(path, mode)
        self._on_read_fn = on_read_fn
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.start()

    def _thread_body(self):
        while True:
            where = self._file.tell()
            data = self._file.read(1024)
            if not data:
                time.sleep(1)
                # required for to get python2 working (Issue #50)
                self._file.seek(where)
            else:
                self._on_read_fn(data)


class FileEventHandler(object):
    def __init__(self, file_path, save_name, api):
        self.file_path = file_path
        self.save_name = save_name
        self._api = api

    def on_created(self):
        pass

    def on_modified(self):
        pass

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


class FileEventHandlerTextStream(FileEventHandler):
    def __init__(self, *args, **kwargs):
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

        self._tailer = FileTailer(self.file_path, on_read)


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

    def __init__(self, api, run, project=None, tags=[], cloud=True, job_type="train", port=None, program=None):
        self._api = api
        self._run = run
        self._cloud = cloud
        self._port = port

        self._project = project if project else api.settings("project")
        self._tags = tags
        self._watch_dir = self._run.dir

        logger.debug("Initialized sync for %s/%s", self._project, self._run.id)

        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.on_file_created
        self._handler.on_modified = self.on_file_modified
        self.url = self._run.get_url(api)
        self._observer = Observer()

        self._observer.schedule(self._handler, self._watch_dir, recursive=True)

        self._config = run.config

        self._stats = stats.Stats()
        # This starts a thread to write system stats every 30 seconds
        self._system_stats = stats.SystemStats(run)
        self._meta = meta.Meta(api, self._run.dir)
        self._meta.data["jobType"] = job_type
        if program:
            self._meta.data["program"] = program

        def push_function(save_name, path):
            with open(path, 'rb') as f:
                self._api.push(self._project, {save_name: f}, run=self._run.id,
                               progress=lambda _, total: self._stats.update_progress(path, total))
        self._file_pusher = file_pusher.FilePusher(push_function)

        self._event_handlers = {}

        self._handler._patterns = [
            os.path.join(self._watch_dir, os.path.normpath('*'))]
        # Ignore hidden files/folders and output.log because we stream it specially
        self._handler._ignore_patterns = [
            '*/.*',
            '*.tmp',
            os.path.join(self._run.dir, OUTPUT_FNAME)
        ]

        self._socket = wandb_socket.Client(self._port)

        if self._cloud:
            self._observer.start()

            self._api.save_patches(self._watch_dir)

            wandb.termlog("Syncing %s" % self.url)
            wandb.termlog('Run directory: %s' % os.path.relpath(run.dir))
            wandb.termlog()

            self._api.get_file_stream_api().set_file_policy(
                OUTPUT_FNAME, CRDedupeFilePolicy())

    def _get_stdout_stderr_streams(self):
        """Sets up STDOUT and STDERR streams. Only call this once."""
        if six.PY2:
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
                fs_api, OUTPUT_FNAME, prepend_timestamp=True)
            self._stderr_stream = streaming_log.TextStreamPusher(
                fs_api, OUTPUT_FNAME, line_prepend='ERROR',
                prepend_timestamp=True)

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

        try:
            self.proc = subprocess.Popen(
                command,
                env=env,
                stdout=self._stdout_tee.tee_file,
                stderr=self._stderr_tee.tee_file
            )
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

        exitcode = None
        try:
            while True:
                res = bytearray()
                try:
                    res = self._socket.recv(2)
                except socket.timeout:
                    pass
                if len(res) == 2 and res[0] == 2:
                    exitcode = res[1]
                    break
                elif len(res) > 0:
                    wandb.termerror(
                        "Invalid message received from child process: %s" % str(res))
                    break
                else:
                    exitcode = self.proc.poll()
                    if exitcode is not None:
                        break
                    time.sleep(1)
        except KeyboardInterrupt:
            exitcode = 255
            wandb.termlog('Ctrl-c pressed; waiting for program to end.')
            keyboard_interrupt_time = time.time()
            if not headless:
                # give the process a couple of seconds to die, then kill it
                while self.proc.poll() is None and (time.time() - keyboard_interrupt_time) < 2:
                    time.sleep(0.1)
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
        wandb.termlog()

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
        self._close_stdout_stderr_streams(exitcode or 254)

        # If we're not syncing to the cloud, we're done
        if not self._cloud:
            self._socket.done()
            return None

        # Show run summary/history
        if self._run.has_summary:
            summary = self._run.summary.summary
            wandb.termlog('Run summary:')
            max_len = max([len(k) for k in summary.keys()])
            format_str = '  {:>%s} {}' % max_len
            for k, v in summary.items():
                wandb.termlog(format_str.format(k, v))
        if self._run.has_history:
            history_keys = self._run.history.keys()
            wandb.termlog('Run history:')
            max_len = max([len(k) for k in history_keys])
            for key in history_keys:
                vals = util.downsample(self._run.history.column(key), 40)
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
        time.sleep(2)
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

        for handler in self._event_handlers.values():
            handler.finish()
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
            wandb.termerror('Sync failed %s' % self.url)
        else:
            wandb.termlog('Synced %s' % self.url)

        if headless:
            self._socket.done()

    def _get_handler(self, file_path, save_name):
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
            elif save_name == 'wandb-summary.json':
                # Load the summary into the syncer process for meta etc to work
                self._run.summary.load()
                self._event_handlers[save_name] = FileEventHandlerOverwrite(
                    file_path, save_name, self._api, self._file_pusher)
            else:
                self._event_handlers[save_name] = FileEventHandlerOverwriteDeferred(
                    file_path, save_name, self._api, self._file_pusher)
        return self._event_handlers[save_name]

    # TODO: limit / throttle the number of adds / pushes
    def on_file_created(self, event):
        if os.path.isdir(event.src_path):
            return None
        save_name = os.path.relpath(event.src_path, self._watch_dir)
        self._get_handler(event.src_path, save_name).on_created()

    # TODO: is this blocking the main thread?
    def on_file_modified(self, event):
        if os.path.isdir(event.src_path):
            return None
        save_name = os.path.relpath(event.src_path, self._watch_dir)
        self._get_handler(event.src_path, save_name).on_modified()
