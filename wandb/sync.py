import psutil, os, stat, sys, time, traceback
from tempfile import NamedTemporaryFile
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from .streaming_log import StreamingLog
from shortuuid import ShortUUID
import atexit
from threading import Thread
from .config import Config
import logging
logger = logging.getLogger(__name__)

class Echo(object):
    def __init__(self, log):
        self.terminal = sys.stdout
        self.log = log

    def write(self, message):
        self.terminal.write(message)
        #TODO: ThreadPool
        self.thread = Thread(target=self.log.write, args=(message,))
        self.thread.start()

    def flush(self):
        self.terminal.flush()

    def close(self, failed=False):
        self.thread.join()
        if failed:
            #TODO: unfortunate line_buffer access
            self.log.push([[self.log.line_buffer.line_number + 1, "ERROR: %s" % failed, "error"]])
            sys.stderr.write("ERROR: %s" % failed)
            failed = True
        self.log.heartbeat(complete=True, failed=failed)

class ExitHooks(object):
    def __init__(self):
        self.exit_code = None
        self.exception = None

    def hook(self):
        self._orig_exit = sys.exit
        sys.exit = self.exit
        sys.excepthook = self.exc_handler

    def exit(self, code=0):
        self.exit_code = code
        self._orig_exit(code)

    def exc_handler(self, exc_type, exc, *args):
        self.exception = exc

class Sync(object):
    """Watches for files to change and automatically pushes them
    """
    def __init__(self, api, run=None, project=None, tags=[], config={}, description=None):
        #1.6 million 6 character combinations
        runGen = ShortUUID(alphabet=list("0123456789abcdefghijklmnopqrstuvwxyz"))
        self.run = run or runGen.random(6)
        self._project = project or api.config("project")
        self._entity = api.config("entity")
        logger.debug("Initialized sync for %s/%s", self._project, self.run)
        self._dpath = ".wandb/description.md"
        self._description = description or os.path.exists(self._dpath) and open(self._dpath).read()
        self.config = Config(config)
        self._proc = psutil.Process(os.getpid())
        self._api = api
        self._tags = tags
        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.add
        self._handler.on_modified = self.push
        self.url = "{base}/{entity}/{project}/runs/{run}".format(
            project=self._project,
            entity=self._entity,
            run=self.run,
            base="https://app.wandb.ai"
        )
        self.log = StreamingLog(self.run)
        self._hooks = ExitHooks()
        self._hooks.hook()
        self._observer = Observer()
        self._observer.schedule(self._handler, os.getcwd(), recursive=True)

    def watch(self, files=[]):
        try:
            self._api.upsert_bucket(name=self.run, project=self._project, entity=self._entity, 
                config=self.config.__dict__, description=self._description)
            if len(files) > 0:
                self._handler._patterns = ["*"+file for file in files]
            else:
                self._handler._patterns = ["*.h5", "*.hdf5", "*.json", "*.meta", "*checkpoint*"]
            self._observer.start()
            print("Syncing %s" % self.url)
            # Piped mode
            if self.source_proc:
                self.log.write(" ".join(self.source_proc.cmdline())+"\n\n")
                line = sys.stdin.readline()
                while line:
                    sys.stdout.write(line)
                    self.log.write(line)
                    #TODO: push log every few minutes...
                    line = sys.stdin.readline()
                self.stop()
            else:
                self.log.write(" ".join(psutil.Process(os.getpid()).cmdline())+"\n\n")
                # let's hijack stdout
                sys.stdout = Echo(self.log)
                logger.debug("Swapped stdout")
                #TODO: stderr
                atexit.register(self.stop)
        except KeyboardInterrupt:
            self.stop()
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print("!!! Fatal W&B Error: %s" % exc_value)
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.error('\n'.join(lines))

    def stop(self):
        #Wait for changes
        time.sleep(0.1)
        self.log.tempfile.flush()
        print("Pushing log")
        slug = "{project}/{run}".format(
            project=self._project,
            run=self.run
        )
        self._api.push(slug, {"training.log": open(self.log.tempfile.name, "rb")})
        os.path.exists(self._dpath) and os.remove(self._dpath)
        print("Synced %s" % self.url)
        sys.stdout.close(failed=self._hooks.exception)
        self.log.close()
        try:
            self._observer.stop()
            self._observer.join()
        #TODO: py2 TypeError: PyCObject_AsVoidPtr called with null pointer
        except TypeError:
            pass
        #TODO: py3 SystemError: <built-in function stop> returned a result with an error set
        except SystemError:
            pass

    #TODO: limit / throttle the number of adds / pushes
    def add(self, event):
        self.push(event)

    #TODO: is this blocking the main thread?
    def push(self, event):
        if os.stat(event.src_path).st_size == 0 or os.path.isdir(event.src_path):
            return None
        fileName = event.src_path.split("/")[-1]
        if logger.parent.handlers[0]:
            debugLog = logger.parent.handlers[0].stream
        else:
            debugLog = None
        self._api.push(self._project, [fileName], bucket=self.run, 
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
