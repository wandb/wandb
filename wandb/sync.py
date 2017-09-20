import psutil
import os
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
from wandb import __stage_dir__, Error
from wandb import streaming_log
from wandb import util
from .api import BinaryFilePolicy, CRDedupeFilePolicy
from .wandb_run import Run
logger = logging.getLogger(__name__)


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

    def write(self, message):
        #print('writing to orig: ', self._orig_stream)
        self._orig_stream.write(message)
        # print('queueing')
        self._queue.put(message)

    def flush(self):
        self._orig_stream.flush()

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
            data = self._file.read(1024)
            if data == '':
                time.sleep(1)
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


class FileEventHandlerOverwrite(FileEventHandler):
    def __init__(self, file_path, save_name, api, project, run_id, *args, **kwargs):
        super(FileEventHandlerOverwrite, self).__init__(
            file_path, save_name, api, *args, **kwargs)
        self._project = project
        self._run_id = run_id
        self._tailer = None

    def on_created(self):
        self.on_modified()

    def on_modified(self):
        print("Pushing %s" % self.file_path)
        with open(self.file_path, 'rb') as f:
            self._api.push(self._project, {self.save_name: f}, run=self._run_id,
                           progress=False)


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

    def __init__(self, api, run_id, config=None, project=None, tags=[], datasets=[], description=None, dir=None):
        # 1.6 million 6 character combinations
        self._run_id = run_id
        self._project = project or api.settings("project")
        self._entity = api.settings("entity")
        logger.debug("Initialized sync for %s/%s", self._project, self._run_id)
        self._dpath = os.path.join(__stage_dir__, 'description.md')
        self._description = description or (os.path.exists(self._dpath) and open(
            self._dpath).read()) or os.getenv('WANDB_DESCRIPTION')
        try:
            self.tty = sys.stdin.isatty() and os.getpgrp() == os.tcgetpgrp(sys.stdout.fileno())
        except OSError:
            self.tty = False
        if not os.getenv('DEBUG') and not self._description and self.tty:
            self._description = editor()
            if self._description is None:
                sys.stderr.write('No description provided, aborting run.\n')
                sys.exit(1)
        self._proc = psutil.Process(os.getpid())
        self._api = api
        self._tags = tags
        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.on_file_created
        self._handler.on_modified = self.on_file_modified
        base_url = api.settings('base_url')
        if base_url.endswith('.dev'):
            base_url = 'http://app.dev'
        self.url = "{base}/{entity}/{project}/runs/{run}".format(
            project=self._project,
            entity=self._entity,
            run=self._run_id,
            base=base_url
        )
        self._hooks = ExitHooks()
        self._hooks.hook()
        self._observer = Observer()
        if dir is None:
            self._watch_dir = os.path.join(
                __stage_dir__, 'run-%s' % self._run_id)
            util.mkdir_exists_ok(self._watch_dir)
        else:
            self._watch_dir = os.path.abspath(dir)

        self._observer.schedule(self._handler, self._watch_dir, recursive=True)

        if config is None:
            config = Config()
        self._config = config

        self._event_handlers = {}

    def watch(self, files):
        try:
            # TODO: better failure handling
            self._api.upsert_run(name=self._run_id, project=self._project, entity=self._entity,
                                 config=self._config.__dict__, description=self._description, host=socket.gethostname())
            self._handler._patterns = [
                os.path.join(self._watch_dir, os.path.normpath(f)) for f in files]
            # Ignore hidden files/folders
            self._handler._ignore_patterns = ['*/.*']
            if os.path.exists(__stage_dir__ + "diff.patch"):
                self._api.push("{project}/{run}".format(
                    project=self._project,
                    run=self._run_id
                ), {"diff.patch": open(__stage_dir__ + "diff.patch", "rb")})
            self._observer.start()

            print("Syncing %s" % self.url)

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
        except KeyboardInterrupt:
            self.stop()
        except Error:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print("!!! Fatal W&B Error: %s" % exc_value)
            lines = traceback.format_exception(
                exc_type, exc_value, exc_traceback)
            logger.error('\n'.join(lines))

    def stop(self):
        # This is a a heuristic delay to catch files that were written just before
        # the end of the script. This is unverified, but theoretically the file
        # change notification process used by watchdog (maybe inotify?) is
        # asynchronous. It's possible we could miss files if 10s isn't long enough.
        # TODO: Guarantee that all files will be saved.
        print("Script ended, waiting for final file modifications.")
        time.sleep(10.0)
        # self.log.tempfile.flush()
        print("Pushing log")
        slug = "{project}/{run}".format(
            project=self._project,
            run=self._run_id
        )
        # self._api.push(
        #    slug, {"training.log": open(self.log.tempfile.name, "rb")})
        os.path.exists(self._dpath) and os.remove(self._dpath)
        print("Synced %s" % self.url)
        self._stdout_stream.close()
        self._stderr_stream.close()
        self._api.get_file_stream_api().finish(self._hooks.exception)
        try:
            self._observer.stop()
            self._observer.join()
        # TODO: py2 TypeError: PyCObject_AsVoidPtr called with null pointer
        except TypeError:
            pass
        # TODO: py3 SystemError: <built-in function stop> returned a result with an error set
        except SystemError:
            pass

    def _get_handler(self, file_path, save_name):
        if save_name not in self._event_handlers:
            if save_name == 'wandb-history.jsonl':
                self._event_handlers['wandb-history.jsonl'] = FileEventHandlerTextStream(
                    file_path, 'wandb-history.jsonl', self._api)
            elif 'tfevents' in save_name:
                # TODO: This is hard-coded, but we want to give users control
                # over streaming files (or detect them).
                self._api.get_file_stream_api().set_file_policy(save_name,
                                                                BinaryFilePolicy())
                self._event_handlers[save_name] = FileEventHandlerBinaryStream(
                    file_path, save_name, self._api)
            else:
                self._event_handlers[save_name] = FileEventHandlerOverwrite(
                    file_path, save_name, self._api, self._project, self._run_id)
        return self._event_handlers[save_name]

    # TODO: limit / throttle the number of adds / pushes
    def on_file_created(self, event):
        if os.stat(event.src_path).st_size == 0 or os.path.isdir(event.src_path):
            return None
        save_name = os.path.relpath(event.src_path, self._watch_dir)
        self._get_handler(event.src_path, save_name).on_created()

    # TODO: is this blocking the main thread?
    def on_file_modified(self, event):
        if os.stat(event.src_path).st_size == 0 or os.path.isdir(event.src_path):
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

    def echo(self):
        print(sys.stdin.read())
