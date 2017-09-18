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
from .run import Run
logger = logging.getLogger(__name__)


def editor(content='', marker='# Before we start this run, enter a brief description. (to skip, direct stdin to dev/null: `python train.py < /dev/null`)\n'):
    message = click.edit(content + '\n\n' + marker)
    if message is not None:
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


class Sync(object):
    """Watches for files to change and automatically pushes them
    """

    def __init__(self, api, run=None, project=None, tags=[], datasets=[], config={}, description=None, dir=None):
        # 1.6 million 6 character combinations
        runGen = ShortUUID(alphabet=list(
            "0123456789abcdefghijklmnopqrstuvwxyz"))
        self.run_id = run or runGen.random(6)
        self._project = project or api.settings("project")
        self._entity = api.settings("entity")
        logger.debug("Initialized sync for %s/%s", self._project, self.run_id)
        self._dpath = os.path.join(__stage_dir__, 'description.md')
        self._description = description or (os.path.exists(self._dpath) and open(
            self._dpath).read()) or os.getenv('WANDB_DESCRIPTION')
        try:
            self.tty = sys.stdin.isatty() and os.getpgrp() == os.tcgetpgrp(sys.stdout.fileno())
        except OSError:
            self.tty = False
        if not os.getenv('DEBUG') and not self._description and self.tty:
            self._description = editor()
        self._config = Config(config)
        self._proc = psutil.Process(os.getpid())
        self._api = api
        self._tags = tags
        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.add
        self._handler.on_modified = self.push
        base_url = api.settings('base_url')
        if base_url.endswith('.dev'):
            base_url = 'http://app.dev'
        self.url = "{base}/{entity}/{project}/runs/{run}".format(
            project=self._project,
            entity=self._entity,
            run=self.run_id,
            base=base_url
        )
        self._hooks = ExitHooks()
        self._hooks.hook()
        self._observer = Observer()
        if dir is None:
            self._watch_dir = os.path.join(
                __stage_dir__, 'run-%s' % self.run_id)
            util.mkdir_exists_ok(self._watch_dir)
        else:
            self._watch_dir = os.path.abspath(dir)

        self._observer.schedule(self._handler, self._watch_dir, recursive=True)

        self.run = Run(self.run_id, self._watch_dir, self._config)
        self._api.set_current_run(self.run_id)

    def watch(self, files):
        try:
            # TODO: better failure handling
            self._api.upsert_run(name=self.run_id, project=self._project, entity=self._entity,
                                 config=self._config.__dict__, description=self._description, host=socket.gethostname())
            self._handler._patterns = [
                os.path.join(self._watch_dir, os.path.normpath(f)) for f in files]
            # Ignore hidden files/folders
            self._handler._ignore_patterns = ['*/.*']
            if os.path.exists(__stage_dir__ + "diff.patch"):
                self._api.push("{project}/{run}".format(
                    project=self._project,
                    run=self.run_id
                ), {"diff.patch": open(__stage_dir__ + "diff.patch", "rb")})
            self._observer.start()

            print("Syncing %s" % self.url)

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
            run=self.run_id
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

    # TODO: limit / throttle the number of adds / pushes
    def add(self, event):
        self.push(event)

    # TODO: is this blocking the main thread?
    def push(self, event):
        if os.stat(event.src_path).st_size == 0 or os.path.isdir(event.src_path):
            return None
        file_name = os.path.relpath(event.src_path, self._watch_dir)
        if logger.parent.handlers[0]:
            debugLog = logger.parent.handlers[0].stream
        else:
            debugLog = None
        print("Pushing %s" % file_name)
        with open(event.src_path, 'rb') as f:
            self._api.push(self._project, {file_name: f}, run=self.run_id,
                           description=self._description, progress=debugLog)

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
