import psutil
import os
import signal
import socket
import stat
import subprocess
import sys
import time
import traceback
from tempfile import NamedTemporaryFile
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from shortuuid import ShortUUID
from .config import Config
import logging
import threading
from six.moves import queue
import click

import wandb
from wandb import Error
from wandb import io_wrap
from wandb import file_pusher
from wandb import stats
from wandb import streaming_log
from wandb import util
from wandb import wandb_run
from .api import BinaryFilePolicy, CRDedupeFilePolicy
logger = logging.getLogger(__name__)

ERROR_STRING = click.style('ERROR', bg='red', fg='green')


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
            pusher.write(data)

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


class Sync(object):
    """Watches for files to change and automatically pushes them
    """

    def __init__(self, api, run, program, args, env, project=None, tags=[]):
        self.cleaned_up = False
        self._api = api
        self._run = run
        self._command = [program] + list(args)
        runner = util.find_runner(program)
        if runner:
            self._command = runner + self._command

        self._project = project if project else api.settings("project")
        self._tags = tags
        self._watch_dir = self._run.dir
        
        logger.debug("Initialized sync for %s/%s", self._project, self._run.id)

        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.on_file_created
        self._handler.on_modified = self.on_file_modified
        self.url = run.get_url(api)
        self._observer = Observer()

        self._observer.schedule(self._handler, self._watch_dir, recursive=True)

        self._config = run.config

        self._stats = stats.Stats()
        # This starts a thread to write system stats every 30 seconds
        self._system_stats = stats.SystemStats(run)

        def push_function(save_name, path):
            with open(path, 'rb') as f:
                self._api.push(self._project, {save_name: f}, run=self._run.id,
                               progress=lambda _, total: self._stats.update_progress(path, total))
        self._file_pusher = file_pusher.FilePusher(push_function)

        self._event_handlers = {}

        # create a handler for description.md, so that we'll save it at the end
        # of the run.
        #self._get_handler(self._run.description_path, wandb_run.DESCRIPTION_FNAME)

        self._handler._patterns = [
            os.path.join(self._watch_dir, os.path.normpath('*'))]
        # Ignore hidden files/folders
        self._handler._ignore_patterns = ['*/.*', '*.tmp']
        self._observer.start()

        self._api.save_patches(self._watch_dir)

        wandb.termlog("Syncing %s" % self.url)

        self._api.get_file_stream_api().set_file_policy(
            'output.log', CRDedupeFilePolicy())
        # Tee stdout/stderr into our TextOutputStream, which will push lines to the cloud.
        self._stdout_stream = streaming_log.TextStreamPusher(
            self._api.get_file_stream_api(), 'output.log', prepend_timestamp=True)
        self._stderr_stream = streaming_log.TextStreamPusher(
            self._api.get_file_stream_api(), 'output.log', line_prepend='ERROR',
            prepend_timestamp=True)

        self._stdout_stream.write(" ".join(psutil.Process(
            os.getpid()).cmdline()) + "\n\n")

        self._stdout_tee = io_wrap.Tee.pty(sys.stdout, self._stdout_stream)
        self._stderr_tee = io_wrap.Tee.pty(sys.stderr, self._stderr_stream)

        try:
            self.proc = subprocess.Popen(
                    self._command,
                    env=env,
                    stdout=self._stdout_tee.tee_file,
                    stderr=self._stderr_tee.tee_file
            )
        except (OSError, IOError):
            raise ClickException('Could not find program: %s' % command)

    def is_running(self):
        return self.proc.poll() is None

    def poll(self):
        terminated = self.proc.poll() is not None
        if self.cleaned_up is not terminated:
            self.clean_up(bool(self.proc.returncode))
        return self.proc.returncode

    def clean_up(self, success):
        if self.cleaned_up:
            return
        self.cleaned_up = True

        self._system_stats.shutdown()

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

        self._stdout_tee.close_join()
        self._stderr_tee.close_join()
        self._stdout_stream.close()
        self._stderr_stream.close()
        self._api.get_file_stream_api().finish(success)

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
                if fname == 'wandb-history.h5' or 'output.log':
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
                wandb.termlog(
                    '%s: %s (%s) did not match uploaded file (%s) md5' % (
                        ERROR_STRING, local_path, local_md5, remote_md5))
        else:
            print('verified!')

        if error:
            wandb.termlog('%s: Sync failed %s' % (ERROR_STRING, self.url))
        else:
            wandb.termlog('Synced %s' % self.url)

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
