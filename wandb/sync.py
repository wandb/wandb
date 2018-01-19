import psutil
import os
import signal
import stat
import sys
import time
import traceback
from tempfile import NamedTemporaryFile
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from shortuuid import ShortUUID
import atexit
from .config import Config
import logging
import threading
from six.moves import queue
import socket
import click
import wandb
from wandb import __stage_dir__, Error
from wandb import file_pusher
from wandb import sparkline
from wandb import stats
from wandb import streaming_log
from wandb import util
from .api import BinaryFilePolicy, CRDedupeFilePolicy
from .wandb_run import Run
logger = logging.getLogger(__name__)

ERROR_STRING = click.style('ERROR', bg='red', fg='green')


def editor(content='', marker='# Before we start this run, enter a brief description. (to skip, direct stdin to dev/null: `python train.py < /dev/null`)\n'):
    message = click.edit(content + '\n\n' + marker)
    if message is None:
        return None
    return message.split(marker, 1)[0].rstrip('\n')


class OutStreamTee(object):
    """Tees a writable filelike object.

    writes/flushes to the passed in stream will go to the stream
    and a second stream.
    """

    def __init__(self, stream, second_stream):
        """Constructor.

        Args:
            stream: stream to tee.
            second_stream: stream to duplicate writes to.
        """
        self._orig_stream = stream
        self._second_stream = second_stream
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._thread.start()

    def _thread_body(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            self._second_stream.write(item)

    def fileno(self):
        return self._orig_stream.fileno()

    def write(self, message):
        self._orig_stream.write(message)
        self._queue.put(message)

    def flush(self):
        self._orig_stream.flush()

    def isatty(self):
        return self._orig_stream.isatty()

    def close(self):
        self._queue.put(None)


class ExitHooks(object):
    def __init__(self):
        self.exit_code = None
        self.exception = None

    def hook(self):
        self._orig_exit = sys.exit
        self._orig_excepthook = sys.excepthook
        sys.exit = self.exit
        sys.excepthook = self.excepthook

    def exit(self, code=0):
        self.exit_code = code
        self._orig_exit(code)

    def excepthook(self, exc_type, exc, *args):
        self.exception = exc
        self._orig_excepthook(exc_type, exc, *args)


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

    def __init__(self, api, job_type, run, config=None, project=None, tags=[], datasets=[], description=None, sweep_id=None):
        self._job_type = job_type
        self._run = run
        self._sweep_id = sweep_id
        self._watch_dir = os.path.abspath(self._run.dir)
        self._project = project or api.settings("project")
        self._entity = api.settings("entity")
        self._signal = None
        logger.debug("Initialized sync for %s/%s", self._project, self._run.id)

        # Load description and write it to the run directory.
        dpath = os.path.join(self._watch_dir, 'description.md')
        self._description = description
        if not self._description:
            if os.path.exists(dpath):
                with open(dpath) as f:
                    self._description = f.read()
            else:
                self._description = os.getenv('WANDB_DESCRIPTION')
        try:
            self.tty = (sys.stdin.isatty() and
                        os.getpgrp() == os.tcgetpgrp(sys.stdout.fileno()))  # check if background process
        except AttributeError:  # windows
            self.tty = sys.stdin.isatty()  # TODO Check for background process in windows
        except OSError:
            self.tty = False

        if not self._description:
            #self._description = editor()
            self._description = self._run.id
        with open(dpath, 'w') as f:
            f.write(self._description)

        self._proc = psutil.Process(os.getpid())
        self._api = api
        self._tags = tags
        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.on_file_created
        self._handler.on_modified = self.on_file_modified
        self.url = "{base}/{entity}/{project}/runs/{run}".format(
            project=self._project,
            entity=self._entity,
            run=self._run.id,
            base=api.app_url
        )
        self._hooks = ExitHooks()
        self._hooks.hook()
        self._observer = Observer()

        self._observer.schedule(self._handler, self._watch_dir, recursive=True)

        if config is None:
            config = Config()
        self._config = config

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
        self._get_handler(dpath, 'description.md')

        try:
            signal.signal(signal.SIGQUIT, self._debugger)
        except AttributeError:
            pass

    def _debugger(self, *args):
        import pdb
        pdb.set_trace()

    def watch(self, files, show_run=False):
        try:
            host = socket.gethostname()
            # handle non-git directories
            root = self._api.git.root
            remote_url = self._api.git.remote_url
            if not root:
                root = os.path.abspath(os.getcwd())
                remote_url = 'file://%s%s' % (host, root)

            program_path = os.path.relpath(
                wandb.SCRIPT_PATH, root)
            # TODO: better failure handling
            upsert_result = self._api.upsert_run(name=self._run.id, project=self._project, entity=self._entity,
                                                 config=self._config.as_dict(), description=self._description, host=host,
                                                 program_path=program_path, job_type=self._job_type, repo=remote_url,
                                                 sweep_name=self._sweep_id)
            self._run_storage_id = upsert_result['id']
            self._handler._patterns = [
                os.path.join(self._watch_dir, os.path.normpath(f)) for f in files]
            # Ignore hidden files/folders
            self._handler._ignore_patterns = ['*/.*', '*.tmp']
            self._observer.start()

            self._api.save_patches(self._watch_dir)

            if self._job_type not in ['train', 'eval']:
                wandb.termlog(
                    'Warning: job type: "%s" is non-standard. Use "train" or "eval".')

            wandb.termlog("Syncing %s" % self.url)
            if show_run:
                import webbrowser
                webbrowser.open_new_tab(self.url)

            self._api.get_file_stream_api().set_file_policy(
                'output.log', CRDedupeFilePolicy())
            # Tee stdout/stderr into our TextOutputStream, which will push lines to the cloud.
            self._stdout_stream = streaming_log.TextStreamPusher(
                self._api.get_file_stream_api(), 'output.log', prepend_timestamp=True)
            sys.stdout = OutStreamTee(sys.stdout, self._stdout_stream)
            self._stderr_stream = streaming_log.TextStreamPusher(
                self._api.get_file_stream_api(), 'output.log', line_prepend='ERROR',
                prepend_timestamp=True)
            sys.stderr = OutStreamTee(sys.stderr, self._stderr_stream)

            self._stdout_stream.write(" ".join(psutil.Process(
                os.getpid()).cmdline()) + "\n\n")

            logger.debug("Swapped stdout/stderr")

            atexit.register(self.stop)
            signal.signal(signal.SIGTERM, self._sigkill)
        except KeyboardInterrupt:
            self.stop()
        except Error:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            wandb.termlog('%s: An Exception was raised during setup, see %s for full traceback.' % (
                (ERROR_STRING, util.get_log_file_path())))
            wandb.termlog("%s: %s" % (ERROR_STRING, exc_value))
            if 'permission' in str(exc_value):
                wandb.termlog(
                    '%s: Are you sure you provided the correct API key to "wandb login"?' % ERROR_STRING)
            lines = traceback.format_exception(
                exc_type, exc_value, exc_traceback)
            logger.error('\n'.join(lines))
            sys.exit(1)

    def update_config(self, config):
        self._config = config
        self._api.upsert_run(id=self._run_storage_id,
                             config=self._config.as_dict())

    def _sigkill(self, *args):
        self._signal = signal.SIGTERM
        # Send keyboard interrupt to ourself! This triggers the python behavior of stopping the
        # running script, and since we've hooked into the exception handler we'll then run
        # stop.
        # This is ugly, but we're planning to move sync to an external process which will
        # solve it.
        os.kill(os.getpid(), signal.SIGINT)

    def stop(self):
        wandb.termlog()
        if self._signal == signal.SIGTERM:
            wandb.termlog(
                'Script ended because of SIGTERM, press ctrl-c to abort syncing.')
        elif isinstance(self._hooks.exception, KeyboardInterrupt):
            wandb.termlog(
                'Script ended because of ctrl-c, press ctrl-c again to abort syncing.')
        elif self._hooks.exception:
            wandb.termlog(
                'Script ended because of Exception, press ctrl-c to abort syncing.')
        else:
            wandb.termlog('Script ended.')
        self._system_stats.shutdown()

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
        time.sleep(2)
        try:
            self._observer.stop()
            self._observer.join()
        # TODO: py2 TypeError: PyCObject_AsVoidPtr called with null pointer
        except TypeError:
            pass
        # TODO: py3 SystemError: <built-in function stop> returned a result with an error set
        except SystemError:
            pass

        self._stdout_stream.close()
        self._stderr_stream.close()
        self._api.get_file_stream_api().finish(self._hooks.exception)

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

    @property
    def source_proc(self):
        mode = os.fstat(0).st_mode
        if not stat.S_ISFIFO(mode):
            # stdin is not a pipe
            return None
        else:
            source = self._proc.parent().children()[0]
            return None if source == self._proc else source
