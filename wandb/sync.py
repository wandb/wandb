import psutil, os, stat, sys, time
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
        t = Thread(target=self.log.write, args=(message,))
        t.start()

    def flush(self):
        self.terminal.flush()

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
        self._config = Config(config)
        self._proc = psutil.Process(os.getpid())
        self._api = api
        self._tags = tags
        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.add
        self._handler.on_modified = self.push
        self.log = StreamingLog(self.run)
        self._observer = Observer()
        self._observer.schedule(self._handler, os.getcwd(), recursive=True)

    def watch(self, files=[]):
        #TODO: Catch errors, potentially retry
        self._api.upsert_bucket(name=self.run, project=self._project, entity=self._entity, 
            config=self._config, description=self._description)
        if len(files) > 0:
            self._handler._patterns = ["*"+file for file in files]
        else:
            self._handler._patterns = ["*.h5", "*.hdf5", "*.json", "*.meta", "*checkpoint*"]
        #TODO: upsert command line
        self._observer.start()
        print("Watching changes for run %s/%s" % (self._project, self.run))
        try:
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
        print("View this run here: https://app.wandb.ai/{entity}/{project}/runs/{run}".format(
            project=self._project,
            entity=self._entity,
            run=self.run
        ))
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
        self._api.push(self._project, [fileName], bucket=self.run, description=self._description, progress=sys.stdout.terminal)

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
