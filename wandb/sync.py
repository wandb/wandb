import psutil, os, stat, sys, time
from tempfile import NamedTemporaryFile
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import atexit

class Logger(object):
    def __init__(self, log):
        self.terminal = sys.stdout
        self.log = log

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)  

    def flush(self):
        #this flush method is needed for python 3 compatibility.
        #this handles the flush command by doing nothing.
        #you might want to specify some extra behavior here.
        pass  

class Sync(object):
    """Watches for files to change and automatically pushes them
    """
    def __init__(self, api, project, bucket="default", description=None):
        self._proc = psutil.Process(os.getpid())
        self._api = api
        self._project = project
        self._bucket = bucket
        self._dpath = ".wandb/description.md"
        self._description = description or os.path.exists(self._dpath) and open(self._dpath).read()
        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.add
        self._handler.on_modified = self.push
        self.log = NamedTemporaryFile("w")
        self._observer = Observer()
        self._observer.schedule(self._handler, os.path.abspath("."), recursive=False)

    def watch(self, files=[]):
        if len(files) > 0:
            self._handler._patterns = files
        #TODO: upsert command line
        self._observer.start()
        print("Watching changes for %s/%s" % (self._project, self._bucket))
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
                sys.stdout = Logger(self.log)
                atexit.register(self.stop)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        #Wait for changes
        time.sleep(0.1)
        self.log.flush()
        print("Pushing log")
        slug = "{project}/{bucket}".format(
            project=self._project,
            bucket=self._bucket
        )
        self._api.push(slug, {"training.log": open(self.log.name, "rb")})
        os.path.exists(self._dpath) and os.remove(self._dpath)
        print("View this run here: https://app.wandb.ai/{entity}/{project}/buckets/{bucket}".format(
            project=self._project,
            entity=self._api.viewer().get('entity', 'models'),
            bucket=self._bucket
        ))
        self.log.close()
        #TODO: maybe move to push?
        self._observer.stop()
        self._observer.join()

    #TODO: limit / throttle the number of adds / pushes
    def add(self, event):
        self.push(event)

    def push(self, event):
        if os.stat(event.src_path).st_size == 0 or os.path.isdir(event.src_path):
            return None
        fileName = event.src_path.split("/")[-1]
        self._api.push(self._project, [fileName], bucket=self._bucket, description=self._description, progress=sys.stdout.terminal)

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
